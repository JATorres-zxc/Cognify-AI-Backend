from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UserNoteViewSet, GeneratedContentViewSet, UserFeedbackViewSet

router = DefaultRouter()
router.register(r'notes', UserNoteViewSet, basename='note')
router.register(r'generated-contents', GeneratedContentViewSet, basename='generated-content')
router.register(r'feedbacks', UserFeedbackViewSet, basename='feedback')

urlpatterns = [
    path('', include(router.urls)),
]