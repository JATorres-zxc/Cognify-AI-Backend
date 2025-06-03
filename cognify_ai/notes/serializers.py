from rest_framework import serializers
from .models import UserNote, GeneratedContent, UserFeedback, GeneratedContentType
from django.conf import settings

class UserNoteSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = UserNote
        fields = ['id', 'user', 'title', 'content', 'file', 'file_url', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at', 'file_url']
        extra_kwargs = {
            'title': {'required': False},
            'content': {'required': False}
        }

    def get_file_url(self, obj):
        if obj.file:
            return self.context['request'].build_absolute_uri(obj.file.url)
        return None

    def validate(self, data):
        if not data.get("content") and not data.get("file"):
            raise serializers.ValidationError("Either content or file must be provided.")
        return data

class GeneratedContentSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeneratedContent
        fields = ['id', 'note', 'content_type', 'content', 'created_at']
        read_only_fields = ['created_at']

class UserFeedbackSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = UserFeedback
        fields = ['id', 'generated_content', 'user', 'rating', 'comments', 'created_at']
        read_only_fields = ['created_at']

class GenerateContentRequestSerializer(serializers.Serializer):
    content_type = serializers.ChoiceField(choices=GeneratedContentType.choices)
    complexity = serializers.ChoiceField(choices=['easy', 'medium', 'hard'], default='medium')
    length = serializers.ChoiceField(choices=['short', 'medium', 'detailed'], default='medium')
    language = serializers.CharField(default='english', max_length=50)