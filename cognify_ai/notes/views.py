from rest_framework.views import APIView
from rest_framework import viewsets, status, permissions
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
import google.generativeai as genai
from django.conf import settings
import json
import logging

import re


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

    def _generate_ai_content(self, note, params):
        content_type = params['content_type']
        prompt = self._build_prompt(note.content, content_type, params)

        # Configure Gemini with your API key
        genai.configure(api_key=settings.GEMINI_API_KEY)

        model = genai.GenerativeModel("gemini-pro")

        try:
            response = model.generate_content(prompt)
            ai_response = response.text  # Get raw string response
        except Exception as e:
            logger.exception("Gemini API call failed")
            raise e

        # Structure AI response
        structured_content = self._structure_ai_response(ai_response, content_type)

        # Save to DB
        generated_content = GeneratedContent.objects.create(
            note=note,
            content_type=content_type,
            content=structured_content,
            generation_parameters=params
        )

        return GeneratedContentSerializer(generated_content, context={'request': self.request}).data

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
        

class TestAIGenerationView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        text = request.data.get("text")
        mode = request.data.get("mode")  # "summary", "flashcards", or "quiz"
        complexity = request.data.get("complexity", "medium")
        language = request.data.get("language", "English")

        if not text or mode not in ["summary", "flashcards", "quiz"]:
            return Response(
                {"error": "Missing or invalid parameters. 'text' and valid 'mode' required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Configure Gemini
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.0-flash")

        prompt = self._build_prompt(text, mode, complexity, language)

        try:
            response = model.generate_content(prompt)
            ai_response = response.text

            # Debug output
            print("=== RAW AI OUTPUT ===")
            print(ai_response)
            print("=====================")

            structured = self._structure_ai_response(ai_response, mode)
            return Response(structured, status=status.HTTP_200_OK)
        except Exception as e:
            logger.exception("Gemini generation failed.")
            return Response({"error": "AI generation failed."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _build_prompt(self, text, mode, complexity, language):
        if mode == "summary":
            return (
                f"Summarize the following text into a concise paragraph. "
                f"Complexity: {complexity}. Language: {language}. "
                f"Return the summary as a JSON object with a 'summary' field.\n\n{text}"
            )
        elif mode == "flashcards":
            return (
                f"Create flashcards from the following text. "
                f"Each flashcard should be returned as a JSON object with 'question' and 'answer'. "
                f"Only return a valid JSON array. Do not include extra text.\n\n"
                f"Complexity: {complexity}. Language: {language}.\n\n{text}"
            )
        elif mode == "quiz":
            return (
                f"Generate multiple-choice quiz questions from the following text. "
                f"Each question must be a JSON object with:\n"
                f"- 'question': the question string\n"
                f"- 'options': an array of 4 choices\n"
                f"- 'answer': the correct answer (must match one of the options)\n\n"
                f"Return a valid JSON array like this:\n"
                f"[{{\"question\": \"...\", \"options\": [\"...\", \"...\", \"...\", \"...\"], \"answer\": \"...\"}}, ...]\n"
                f"No explanation. JSON only.\n\n"
                f"Complexity: {complexity}. Language: {language}.\n\n{text}"
            )

    def _structure_ai_response(self, response_text, mode):
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            if mode == "summary":
                return {"summary": response_text.strip()}

            elif mode == "flashcards":
                flashcards = []
                lines = response_text.strip().split('\n')
                question, answer = None, None

                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    if '?' in line and not line.lower().startswith("a:"):
                        if question and answer:
                            flashcards.append({
                                "question": question.strip(),
                                "answer": answer.strip()
                            })
                        question = line
                        answer = ""
                    elif question:
                        if line.lower().startswith("a:"):
                            answer = line[2:].strip()
                        else:
                            answer += " " + line.strip()

                if question and answer:
                    flashcards.append({
                        "question": question.strip(),
                        "answer": answer.strip()
                    })
                return flashcards

            elif mode == "quiz":
                quiz_items = []
                lines = response_text.strip().split('\n')
                question, options, correct_answer = "", [], ""

                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    if '?' in line and not options:
                        question = line
                        options = []
                    elif re.match(r"^[-\d\.\)]\s*", line):  # e.g., "- Option", "1. Option", "a) Option"
                        option_text = re.sub(r"^[-\d\.\)]\s*", '', line).strip()
                        options.append(option_text)
                    elif line.lower().startswith("answer:"):
                        correct_answer = line.split(":", 1)[1].strip()

                        if question and options and correct_answer:
                            quiz_items.append({
                                "question": question,
                                "options": options,
                                "answer": correct_answer
                            })
                            question, options, correct_answer = "", [], ""

                return quiz_items

        return {"raw_response": response_text}