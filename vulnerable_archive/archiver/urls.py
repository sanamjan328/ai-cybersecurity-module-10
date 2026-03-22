from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="index"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),
    path("register/", views.register, name="register"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("api/token/", views.generate_token, name="generate_token"),
    path("archives/", views.archive_list, name="archive_list"),
    path("archives/add/", views.add_archive, name="add_archive"),
    path("archives/<int:archive_id>/", views.view_archive, name="view_archive"),
    path("archives/<int:archive_id>/edit/", views.edit_archive, name="edit_archive"),
    path(
        "archives/<int:archive_id>/delete/", views.delete_archive, name="delete_archive"
    ),
    path("search/", views.search_archives, name="search_archives"),
    path("ask_db/", views.ask_database, name="ask_database"),
    path("export/", views.export_summary, name="export_summary"),
    path(
        "archives/<int:archive_id>/enrich/", views.enrich_archive, name="enrich_archive"
    ),
]
