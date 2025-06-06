from rest_framework.views import APIView
from rest_framework import viewsets, status, permissions, serializers
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
import fitz
import re

import re
from django.utils.timezone import now, timedelta
import pyclamd



logger = logging.getLogger(__name__)

class UserNoteViewSet(viewsets.ModelViewSet):
    queryset = UserNote.objects.all()
    serializer_class = UserNoteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)

    def scan_file_for_viruses(self, uploaded_file):
        cd = pyclamd.ClamdAgnostic()
        if not cd.ping():
            raise Exception("ClamAV is not running or not reachable.")

        uploaded_file.seek(0)  # ensure beginning
        result = cd.scan_stream(uploaded_file.read())
        uploaded_file.seek(0)  # reset file pointer
        if result is not None:
            raise serializers.ValidationError("Uploaded file is infected with a virus.")

    def perform_create(self, serializer):
        file = self.request.FILES.get("file")
        content = serializer.validated_data.get("content", "").strip()

        # if pdf file, extract its content
        if file and file.name.endswith(".pdf"):
            self.scan_file_for_viruses(file)
            try:
                pdf_content = self._extract_text_from_pdf(file)
                content = content or pdf_content
            except Exception as e:
                logger.exception("PDF extraction failed.")
                raise serializers.ValidationError("Could not extract text from the PDF.")

        serializer.save(user=self.request.user, content=content)

    def _extract_text_from_pdf(self, uploaded_file):
        text = ""
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        for page in doc:
            text += page.get_text()
        doc.close()
        return text.strip()

    def has_reached_daily_limit(self,user):
        today = now().date()
        return GeneratedContent.objects.filter(
            note__user=user,
            created_at__date=today
        ).count() >= settings.MAX_DAILY_GENERATIONS

    @action(detail=False, methods=['get'])
    def quota_status(self, request):
        today = now().date()
        used = GeneratedContent.objects.filter(note__user=request.user, created_at__date=today).count()
        remaining = max(settings.MAX_DAILY_GENERATIONS - used, 0)
        return Response({
            "used": used,
            "remaining": remaining,
            "limit": settings.MAX_DAILY_GENERATIONS
        })

    @action(detail=True, methods=['post'], serializer_class=GenerateContentRequestSerializer)
    def generate_content(self, request, pk=None):
        note = self.get_object()

        if self.has_reached_daily_limit(request.user):
            return Response(
                {"error": "Daily generation limit reached. Try again tomorrow."},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

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
        for model in genai.list_models():
            print(model.name)

        model = genai.GenerativeModel(model_name="models/gemini-1.5-flash")

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
        complexity = params['complexity']
        language = params['language']
        length = params.get('length', 'medium')

        if content_type == 'flashcards':
            return (
                # f"You are a helpful assistant. Generate flashcards from this note. "
                # f"Complexity: {complexity}. Language: {language}. "
                # f"Return as JSON: [{{'question': '...', 'answer': '...'}}].\n\n{note_content}"
                f"Create flashcards from the following text. "
                f"Each flashcard should be returned as a JSON object with 'question' and 'answer'. "
                f"Only return a valid JSON array. Do not include extra text.\n\n"
                f"Complexity: {complexity}. Language: {language}.\n\n{note_content}"

            )
        elif content_type == 'summary':
            return (
                f"Summarize the following text into a {length} summary. "
                f"Complexity: {complexity}. Language: {language}. "
                f"Return as JSON: {{'summary': '...'}}.\n\n{note_content}"
            )
        elif content_type == 'quiz_questions':
            return (
                # f"Generate quiz questions from this content. Complexity: {complexity}. Language: {language}. "
                # f"Each question must have 4 multiple-choice answers and the correct answer marked. "
                # f"Return as JSON: [{{'question': '...', 'options': [...], 'correct_answer': '...'}}].\n\n{note_content}"
                f"Generate multiple-choice quiz questions from the following text. "
                f"Each question must be a JSON object with:\n"
                f"- 'question': the question string\n"
                f"- 'options': an array of 4 choices\n"
                f"- 'answer': the correct answer (must match one of the options)\n\n"
                f"Return a valid JSON array like this:\n"
                f"[{{\"question\": \"...\", \"options\": [\"...\", \"...\", \"...\", \"...\"], \"answer\": \"...\"}}, ...]\n"
                f"No explanation. JSON only.\n\n"
                f"Complexity: {complexity}. Language: {language}.\n\n{note_content}"
            )
        return note_content

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
                lines = ai_response.strip().split('\n')
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
            
            elif content_type == 'quiz_questions':
                 # Try to extract a valid JSON array from the text using regex
                try:
                    # Extract the first JSON array in the response
                    match = re.search(r'\[\s*\{.*?\}\s*\]', ai_response, re.DOTALL)
                    if match:
                        json_str = match.group(0)
                        return json.loads(json_str)
                except Exception:
                    pass

                # Fallback to custom parsing
                quiz_items = []
                lines = ai_response.strip().split('\n')
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
                # Try to extract a valid JSON array from the text using regex
                try:
                    # Extract the first JSON array in the response
                    match = re.search(r'\[\s*\{.*?\}\s*\]', response_text, re.DOTALL)
                    if match:
                        json_str = match.group(0)
                        return json.loads(json_str)
                except Exception:
                    pass

                # Fallback to custom parsing
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