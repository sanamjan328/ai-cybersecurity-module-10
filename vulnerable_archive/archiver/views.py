import datetime
import ipaddress
import json
import re
import socket
from datetime import timezone
from pathlib import Path
from urllib.parse import urlparse

import jwt
import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify

from .llm_utils import query_llm
from .models import Archive

# Create your views here.

SQL_BLOCKLIST_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|pragma)\b",
    re.IGNORECASE,
)
CLAUSE_SPLIT_RE = re.compile(
    r"\b(group\s+by|order\s+by|limit|offset)\b", re.IGNORECASE
)


def _is_safe_remote_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False

    host = parsed.hostname.lower()
    if host in {"localhost"} or host.endswith(".local"):
        return False

    try:
        addrinfo = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False

    for entry in addrinfo:
        ip_str = entry[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    return True


def _enforce_readonly_scoped_sql(sql_query):
    sql = (sql_query or "").strip().rstrip(";")
    lowered = sql.lower()

    if not lowered.startswith("select "):
        raise ValueError("Only SELECT queries are allowed.")
    if SQL_BLOCKLIST_RE.search(sql):
        raise ValueError("Blocked SQL keyword detected.")
    if " from archiver_archive" not in f" {lowered} ":
        raise ValueError("Query must read from archiver_archive.")
    if " join " in f" {lowered} ":
        raise ValueError("JOINs are not allowed.")

    match = CLAUSE_SPLIT_RE.search(sql)
    if match:
        before_clause = sql[: match.start()].rstrip()
        after_clause = sql[match.start() :].lstrip()
    else:
        before_clause = sql
        after_clause = ""

    if " where " in f" {before_clause.lower()} ":
        scoped_sql = f"{before_clause} AND user_id = ?"
    else:
        scoped_sql = f"{before_clause} WHERE user_id = ?"

    if after_clause:
        scoped_sql = f"{scoped_sql} {after_clause}"

    return scoped_sql


def register(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Registration successful!")
            return redirect("dashboard")
    else:
        form = UserCreationForm()
    return render(request, "archiver/register.html", {"form": form})


@login_required
def dashboard(request):
    return render(request, "archiver/dashboard.html")


@login_required
def generate_token(request):
    payload = {
        "user_id": request.user.id,
        "username": request.user.username,
        "exp": datetime.datetime.now(timezone.utc) + datetime.timedelta(days=1),
    }

    # jwt.encode returns a string in PyJWT >= 2.0.0
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

    return JsonResponse({"token": token})


@login_required
def archive_list(request):
    archives = Archive.objects.filter(user=request.user).order_by("-created_at")
    return render(request, "archiver/archive_list.html", {"archives": archives})


@login_required
def add_archive(request):
    if request.method == "POST":
        url = request.POST.get("url")
        notes = request.POST.get("notes")

        if url:
            try:
                if not _is_safe_remote_url(url):
                    messages.error(request, "Only public HTTP/HTTPS URLs are allowed.")
                    return render(request, "archiver/add_archive.html")

                response = requests.get(url, timeout=10)
                title = "No Title Found"
                if "<title>" in response.text:
                    try:
                        title = (
                            response.text.split("<title>", 1)[1]
                            .split("</title>", 1)[0]
                            .strip()
                        )
                    except IndexError:
                        pass

                Archive.objects.create(
                    user=request.user,
                    url=url,
                    title=title,
                    content=response.text,
                    notes=notes,
                )
                messages.success(request, "URL archived successfully!")
                return redirect("archive_list")
            except Exception as e:
                messages.error(request, f"Failed to archive URL: {str(e)}")

    return render(request, "archiver/add_archive.html")


@login_required
def view_archive(request, archive_id):
    archive = get_object_or_404(Archive, pk=archive_id, user=request.user)
    return render(request, "archiver/view_archive.html", {"archive": archive})


@login_required
def edit_archive(request, archive_id):
    archive = get_object_or_404(Archive, pk=archive_id, user=request.user)

    if request.method == "POST":
        archive.notes = request.POST.get("notes")
        archive.save()
        messages.success(request, "Archive updated successfully!")
        return redirect("archive_list")

    return render(request, "archiver/edit_archive.html", {"archive": archive})


@login_required
def delete_archive(request, archive_id):
    archive = get_object_or_404(Archive, pk=archive_id, user=request.user)

    if request.method == "POST":
        archive.delete()
        messages.success(request, "Archive deleted successfully!")
        return redirect("archive_list")

    return render(request, "archiver/delete_archive.html", {"archive": archive})


@login_required
def search_archives(request):
    query = request.GET.get("q", "")
    results = Archive.objects.filter(user=request.user)
    if query:
        results = results.filter(title__icontains=query)
    results = results.order_by("-created_at")

    return render(request, "archiver/search.html", {"results": results, "query": query})


@login_required
def ask_database(request):
    answer = None
    sql_query = None
    user_input = request.POST.get("prompt", "")

    if request.method == "POST" and user_input:
        # Schema info for the LLM
        schema_info = """
        Table: archiver_archive
        Columns: id, title, url, content, notes, created_at, user_id
        """

        system_prompt = f"""
        You are a SQL expert. Convert the user's natural language query into a raw SQLite SQL query.
        The table name is 'archiver_archive'.
        Do not explain. Return ONLY the SQL query.
        Current User ID: {request.user.id}
        Schema:
        {schema_info}
        """

        # Get SQL from LLM
        sql_query = query_llm(user_input, system_instruction=system_prompt).strip()

        # Clean up markdown code blocks if present
        if "```sql" in sql_query:
            sql_query = sql_query.split("```sql")[1].split("```")[0].strip()
        elif "```" in sql_query:
            sql_query = sql_query.split("```")[1].strip()

        try:
            safe_sql = _enforce_readonly_scoped_sql(sql_query)
            with connection.cursor() as cursor:
                cursor.execute(safe_sql, [request.user.id])
                if cursor.description:
                    columns = [col[0] for col in cursor.description]
                    results = [dict(zip(columns, row)) for row in cursor.fetchall()]
                    answer = results
                else:
                    answer = "Query executed successfully (no results returned)."
        except Exception as e:
            answer = f"Error executing SQL: {str(e)}"

    return render(
        request,
        "archiver/ask_database.html",
        {"answer": answer, "sql_query": sql_query, "prompt": user_input},
    )


@login_required
def export_summary(request):
    if request.method == "POST":
        topic = request.POST.get("topic")
        filename_hint = request.POST.get("filename_hint")

        # Prompt for LLM to generate summary content
        content_prompt = f"Write a short summary about: {topic}"
        summary_content = query_llm(content_prompt)

        base_export_dir = Path(settings.BASE_DIR) / "exported_summaries"
        base_export_dir.mkdir(parents=True, exist_ok=True)
        candidate = filename_hint or topic or "summary"
        safe_name = slugify(candidate)[:80] or "summary"
        file_path = base_export_dir / f"{safe_name}.txt"

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(summary_content)

            messages.success(request, f"Summary written to: {file_path}")
        except Exception as e:
            messages.error(request, f"File Write Error: {str(e)}")

    return render(request, "archiver/export_summary.html")


@login_required
def enrich_archive(request, archive_id):
    archive = get_object_or_404(Archive, pk=archive_id, user=request.user)
    llm_response = None

    if request.method == "POST":
        user_instruction = request.POST.get(
            "instruction", "Summarize this content and find related links."
        )

        system_prompt = """
        You are an AI assistant that enriches archived content.
        You can fetch external data if explicitly requested or if the content implies it.
        """

        prompt = f"""
        User Instruction: {user_instruction}

        Archive Content:
        {archive.content}

        Archive Notes:
        {archive.notes}
        """

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "fetch_url",
                    "description": "Fetch data from a URL",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "The URL to fetch",
                            }
                        },
                        "required": ["url"],
                    },
                },
            }
        ]

        # response is now a message dict when tools are provided
        message = query_llm(prompt, system_instruction=system_prompt, tools=tools)

        # Check for tool calls
        if message.get("tool_calls"):
            tool_calls = message["tool_calls"]
            llm_response = f"LLM decided to use tools:\n{tool_calls}\n\n"

            for tool in tool_calls:
                if tool["function"]["name"] == "fetch_url":
                    arguments = tool["function"].get("arguments", {})
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except json.JSONDecodeError:
                            arguments = {}
                    url_to_fetch = arguments.get("url")
                    if not url_to_fetch:
                        llm_response += "Tool call missing URL argument.\n"
                        continue
                    if not _is_safe_remote_url(url_to_fetch):
                        llm_response += f"Blocked non-public URL: {url_to_fetch}\n"
                        continue
                    try:
                        requests.get(url_to_fetch, timeout=5)
                        llm_response += f"Successfully fetched: {url_to_fetch}\n"
                    except Exception as e:
                        llm_response += f"Failed to fetch {url_to_fetch}: {str(e)}\n"
        else:
            llm_response = message.get("content", "")

    return render(
        request,
        "archiver/enrich_archive.html",
        {"archive": archive, "llm_response": llm_response},
    )
