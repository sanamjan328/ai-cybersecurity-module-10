# 🚨 Vulnerable Archive -- Django Security Lab with LLM Risks

## 📌 Overview

**Vulnerable Archive** is an intentionally insecure Django web
application designed to demonstrate both **classic web vulnerabilities**
and **modern risks introduced by Large Language Model (LLM)
integrations**.

## 🎯 Objectives

-   Demonstrate real-world web vulnerabilities
-   Highlight security risks in AI-powered applications
-   Provide secure vs insecure examples

## ⚠️ Vulnerabilities

-   IDOR
-   SQL Injection
-   XSS
-   SSRF
-   Weak JWT
-   Unsafe LLM → SQL
-   Arbitrary File Write

## 🛠️ Fixes

-   Use ORM
-   Escape inputs
-   Restrict LLM outputs
-   Validate URLs
-   Use environment variables

## 🚀 Run

``` bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

## ⚠️ Disclaimer

For educational use only.
