from django.contrib.auth.models import User
from django.db import models


# Create your models here.
class Archive(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    url = models.URLField(max_length=2000)
    title = models.CharField(max_length=255, blank=True)
    content = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title or self.url} ({self.created_at})"
