from django.db import models
from django.conf import settings
from django.utils import timezone

class UserNote(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    content = models.TextField()
    file = models.FileField(upload_to='user_notes/', null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} - {self.user.email}"

class GeneratedContentType(models.TextChoices):
    FLASHCARDS = 'flashcards', 'Flashcards'
    SUMMARY = 'summary', 'Summary'
    QUIZ_QUESTIONS = 'quiz_questions', 'Quiz Questions'

class GeneratedContent(models.Model):
    note = models.ForeignKey(UserNote, on_delete=models.CASCADE, related_name='generated_contents')
    content_type = models.CharField(max_length=20, choices=GeneratedContentType.choices)
    content = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)
    generation_parameters = models.JSONField(null=True, blank=True)  # stores poarams used for generation

    def __str__(self):
        return f"{self.get_content_type_display()} for {self.note.title}"

class UserFeedback(models.Model):
    generated_content = models.ForeignKey(GeneratedContent, on_delete=models.CASCADE, related_name='feedbacks')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    rating = models.PositiveSmallIntegerField(choices=[(i, str(i)) for i in range(1, 6)])
    comments = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ('generated_content', 'user')

    def __str__(self):
        return f"Feedback by {self.user.email} - {self.rating} stars"