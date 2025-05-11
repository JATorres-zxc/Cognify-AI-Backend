from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import UserNote, GeneratedContent, UserFeedback
from .serializers import (
    UserNoteSerializer,
    GeneratedContentSerializer,
    UserFeedbackSerializer,
    GenerateContentRequestSerializer
)
from django.shortcuts import get_object_or_404
# import openai
from django.conf import settings
import json
import logging

logger = logging.getLogger(__name__)

class UserNoteViewSet(viewsets.ModelViewSet):
    queryset = UserNote.objects.all()
    serializer_class = UserNoteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)

    @action(detail=True, methods=['post'], serializer_class=GenerateContentRequestSerializer)
    def generate_content(self, request, pk=None):
        note = self.get_object()
        serializer = GenerateContentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            generated_content = self._generate_ai_content(note, serializer.validated_data)
            return Response(generated_content, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Error generating content: {str(e)}")
            return Response(
                {"error": "Failed to generate content. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # def _generate_ai_content(self, note, params):
    #     """Generate AI content based on note and parameters"""
    #     content_type = params['content_type']
    #     prompt = self._build_prompt(note.content, content_type, params)
        
    #     # Initialize OpenAI client
    #     # client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        
    #     # response = client.chat.completions.create(
    #     #     model="gpt-3.5-turbo",
    #     #     messages=[{"role": "user", "content": prompt}],
    #     #     temperature=0.7,
    #     # )
        
    #     # ai_response = response.choices[0].message.content
        
    #     # Parse and structure the response based on content type
    #     structured_content = self._structure_ai_response(ai_response, content_type)
        
    #     # Save to database
    #     generated_content = GeneratedContent.objects.create(
    #         note=note,
    #         content_type=content_type,
    #         content=structured_content,
    #         generation_parameters=params
    #     )
        
    #     return GeneratedContentSerializer(generated_content, context={'request': self.request}).data

    def _build_prompt(self, note_content, content_type, params):
        """Build the prompt for OpenAI based on the request"""
        prompts = {
            'flashcards': (
                f"Create flashcards from the following notes. Each flashcard should have a clear question and answer. "
                f"Complexity: {params['complexity']}. Language: {params['language']}. "
                f"Return the flashcards as a JSON array with 'question' and 'answer' fields. "
                f"Notes:\n{note_content}"
            ),
            'summary': (
                f"Create a {params['length']} summary of the following notes. "
                f"Complexity: {params['complexity']}. Language: {params['language']}. "
                f"Return the summary as a JSON object with 'summary' field. "
                f"Notes:\n{note_content}"
            ),
            'quiz_questions': (
                f"Generate {params['complexity']} quiz questions with multiple choice answers from the following notes. "
                f"Include 4 options for each question and mark the correct answer. "
                f"Language: {params['language']}. "
                f"Return as a JSON array with 'question', 'options', and 'correct_answer' fields. "
                f"Notes:\n{note_content}"
            )
        }
        return prompts.get(content_type, prompts['summary'])

    def _structure_ai_response(self, ai_response, content_type):
        """Convert AI response to structured JSON"""
        try:
            # Try to parse as JSON directly
            return json.loads(ai_response)
        except json.JSONDecodeError:
            # If not valid JSON, handle based on content type
            if content_type == 'summary':
                return {'summary': ai_response}
            elif content_type == 'flashcards':
                # Try to parse flashcard format if not JSON
                flashcards = []
                for line in ai_response.split('\n'):
                    if line.strip() and '?' in line:
                        parts = line.split('?')
                        question = parts[0] + '?'
                        answer = '?'.join(parts[1:]).strip()
                        flashcards.append({'question': question, 'answer': answer})
                return flashcards
            elif content_type == 'quiz_questions':
                # Basic parsing for quiz questions if not JSON
                questions = []
                current_question = {}
                for line in ai_response.split('\n'):
                    line = line.strip()
                    if line.startswith('Q:') or line.startswith('Question:'):
                        if current_question:
                            questions.append(current_question)
                        current_question = {'question': line.split(':', 1)[1].strip(), 'options': []}
                    elif line.startswith(('A:', 'B:', 'C:', 'D:', 'Option')):
                        option_parts = line.split(':', 1)
                        if len(option_parts) > 1:
                            current_question['options'].append(option_parts[1].strip())
                    elif line.startswith('Correct answer:'):
                        current_question['correct_answer'] = line.split(':', 1)[1].strip()
                if current_question:
                    questions.append(current_question)
                return questions
            return {'raw_response': ai_response}

class GeneratedContentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = GeneratedContentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return GeneratedContent.objects.filter(note__user=self.request.user)

class UserFeedbackViewSet(viewsets.ModelViewSet):
    serializer_class = UserFeedbackSerializer
    permission_classes = [IsAuthenticated]
    queryset = UserFeedback.objects.all()

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)

    def perform_create(self, serializer):
        generated_content = get_object_or_404(
            GeneratedContent,
            id=serializer.validated_data['generated_content'].id,
            note__user=self.request.user
        )
        serializer.save(user=self.request.user, generated_content=generated_content)