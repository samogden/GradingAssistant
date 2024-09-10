#!env python
from __future__ import annotations

import collections
import io
import logging
import os
import pprint
import shutil
import tempfile
import time
import tkinter as tk
import urllib
from typing import List, Dict, Tuple

import canvasapi
import canvasapi.quiz
import canvasapi.assignment
import canvasapi.upload

import html2text
import pandas as pd
import pymupdf as fitz
import requests.exceptions

import ai_helper
import grader as grader_module
import misc
import question
from misc import get_file_list

logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


class Assignment(misc.Costable):
  """
  An assignment is an individual assignment that will contain a number of Questions,
  each of which contain a number of Responses.
  This will better match the structure of real assignments, and thus be flexible for different sources.
  """
  
  def __init__(self, questions: List[question.Question], **flags):
    self.questions = questions
  
  def __str__(self):
    return f"Assignment({len(self.questions)}questions, {sum([q.max_points for q in self.questions])}points)"
  
  def grade(self, grader: grader_module.Grader):
    # todo actually run the chosen grading flow?
    pass
    
  def get_by_student(self):
    # todo: after grading this function can be used ot get a by-student representation of the questions
    pass

  def get_tkinter_frame(self, parent, grading_helper: ai_helper.AI_Helper) -> tk.Frame:
    frame = tk.Frame(parent)
    
    # Make a scrollbar for the Listbox
    question_scrollbar = tk.Scrollbar(frame)
    question_scrollbar.pack(side=tk.RIGHT, fill=tk.BOTH)
    
    # Make a Listbox for questions
    question_listbox = tk.Listbox(frame, yscrollcommand=question_scrollbar.set)
    
    def redraw_questions():
      question_listbox.delete(0, tk.END)
      for i, q in enumerate(self.questions):
        question_listbox.insert(i, q if any([r.score is None for r in q.responses]) else "completed")
    redraw_questions()
    question_listbox.pack()
    question_listbox.focus()
    
    def doubleclick_callback(_):
      selected_question = self.questions[question_listbox.curselection()[0]]
      new_window = tk.Toplevel(parent)
      question_frame = selected_question.get_tkinter_frame(new_window, grading_helper, callback=redraw_questions)
      question_frame.pack()
    
    # Set up a callback for double-clicking
    question_listbox.bind('<Double-1>', doubleclick_callback)
    
    frame.pack()
    return frame
    
  def autograde(self, grading_helper : ai_helper.AI_Helper, **kwargs):
    for q in self.questions:
      log.debug(f"Question: {q}")
      for r in q.responses:
        log.debug(f"response: {r.student_id}")
        r.update_from_gpt(grading_helper)
        r.score = r.score_gpt
      # break
  
  def get_token_count(self):
    return sum([q.get_token_count() for q in self.questions])

  def get_records(self) -> pd.DataFrame:
    records = []
    for q in self.questions:
      for r in q.responses:
        if r.score is None:
          continue
        records.append({
          "student": r.student_id,
          "input_file": None if not hasattr(r, "input_file") else r.input_file,
          "question": q.question_number,
          "score": r.score,
          "feedback": r.feedback,
          "score_gpt": r.score_gpt,
          "feedback_gpt" : r.feedback_gpt
        })
    df = pd.DataFrame.from_records(records)
    return df

  def get_score_csv(self):
    df = self.get_records()
    df_grouped_and_summed = df.drop(["feedback_gpt"], axis=1).groupby("student").agg({
      'input_file': 'min',
      'question': 'nunique',
      'score': 'sum',
      'score_gpt': 'sum'
    })
    df_grouped_and_summed = df_grouped_and_summed.drop(["question", "score_gpt"], axis=1)
    df_grouped_and_summed.to_csv("grades.csv")
  
  def get_student_feedback(self, feedback_dir="feedback"):
    if os.path.exists(feedback_dir): shutil.rmtree(feedback_dir)
    os.mkdir(feedback_dir)
    df = self.get_records()
    for student in df["student"]:
      student_feedback_df = df[df["student"]==student]
      student_feedback_df.sort_values(by="question")
      student_feedback_df = student_feedback_df[["question", "score", "feedback"]]
      student_feedback_df.to_csv(os.path.join(feedback_dir, f"{student}.csv"), index=False)

  def get_feedback(self):
    self.get_score_csv()
    self.get_student_feedback()

class ScannedExam(Assignment):
  def __init__(self, path_to_base_exam, path_to_scanned_exams, limit=None, **flags):
    files = [os.path.join(f) for f in get_file_list(path_to_scanned_exams) if f.endswith(".pdf")]
    
    if limit is not None:
      files = files[:limit]
    
    # todo: If there is no base exam then default to a per-page grading scheme
    question_locations = QuestionLocation.get_question_locations(path_to_base_exam)
    
    question_responses: collections.defaultdict[int, List[question.Response]] = collections.defaultdict(list)
    
    # Break up each pdf into the responses
    for student_id, f in enumerate(files):
      log.info(f"Loading student {student_id+1}/{len(files)}")
      for q_number, response in question.Response_fromPDF.load_from_pdf(student_id, f, question_locations, **flags).items():
        question_responses[q_number].append(response)
    
    # Make questions from each response
    questions = [
      question.Question(question_number, responses)
      for (question_number, responses) in question_responses.items()
    ]
      
    super().__init__(questions, **flags)

class QuestionLocation:
  def __init__(self, question_number, page_number, location):
    self.question_number = question_number
    self.page_number = page_number
    self.location = location
    # todo: add in a reference snippet
  
  @staticmethod
  def get_question_locations(path_to_base_exam: str) -> List[QuestionLocation]:
    question_locations = []
    
    pdf_doc = fitz.open(path_to_base_exam)
    for page_number, page in enumerate(pdf_doc.pages()):
      # log.debug(f"Looking on {page_number}")
      for question_number in range(30):
        text_instances = page.search_for(f"Question {question_number}:")
        if len(text_instances) > 0:
          question_locations.append(QuestionLocation(question_number, page_number, text_instances[0].tl.y))
    
    return question_locations


class CanvasAssignment(Assignment):
  canvas : canvasapi.Canvas = None
  
  def __init__(self, course_id : int, assignment_id : int, prod=False):
    if self.__class__.canvas is None:
      if prod:
        self.__class__.canvas = canvasapi.Canvas(os.environ.get("CANVAS_API_URL_prod"), os.environ.get("CANVAS_API_KEY_prod"))
      else:
        self.__class__.canvas = canvasapi.Canvas(os.environ.get("CANVAS_API_URL"), os.environ.get("CANVAS_API_KEY"))
    
    self.canvas_course = self.canvas.get_course(course_id)
    self.canvas_assignment = self.canvas_course.get_assignment(assignment_id)
    
    self.working_dir = tempfile.mkdtemp()
    
    super().__init__([])
  
  def __enter__(self):
    return self
  
  def __exit__(self, exc_type, exc_val, exc_tb):
    shutil.rmtree(self.working_dir)
  
  def get_student_submissions(self, canvas_assignment: canvasapi.assignment, only_include_latest=True) -> List[canvasapi.assignment.Submission]:
    log.debug(f"get_student_submission({canvas_assignment}, {only_include_latest})")
    
    return list(self.canvas_assignment.get_submissions(include='submission_history'))
  
  def download_submission_files(self, submissions: List[canvasapi.assignment.Submission], download_all_variations=False):
    log.debug(f"download_submission_files(self, {len(submissions)} submissions)")
    
    # Set up the attachments directory
    attachments_dir = self.working_dir
    if os.path.exists(attachments_dir): shutil.rmtree(attachments_dir)
    os.mkdir(attachments_dir)
    
    submission_files = collections.defaultdict(list)
    
    for student_submission in submissions:
      if student_submission.missing:
        # skip missing assignments
        continue
      log.debug(f"For {student_submission.user_id} there are {len(student_submission.submission_history)} submissions")
      for attempt_number, submission_attempt in enumerate(student_submission.submission_history):
        log.debug(f"Submission #{attempt_number+1} has {len(submission_attempt['attachments'])} variations")
        for attachment in submission_attempt['attachments']:
          local_path = os.path.join(attachments_dir, f"student_{student_submission.user_id}-{attempt_number}_{attachment['id']}_{attachment['filename']}")
          log.debug(f"Downloading {attachment['url']} to {local_path}")
          urllib.request.urlretrieve(attachment['url'], local_path)
          submission_files[(student_submission.user_id, attempt_number)].append(local_path)
        if not download_all_variations:
          continue
        else:
          # Add in a delay because it seems to crashing the API...
          time.sleep(0.1)
    return submission_files

class CanvasQuiz(CanvasAssignment):
  def __init__(self, quiz: canvasapi.quiz.Quiz, course: canvasapi.canvas.Course, all_submissions=False):
    # We want to grab responses and next them withing questions, which we then pass on to the super constructor
    
    canvas_assignment = course.get_assignment(quiz.assignment_id)
    
    h = html2text.HTML2Text()
    h.ignore_links = True
    
    question_responses: collections.defaultdict[int, List[question.Response]] = collections.defaultdict(list)
    question_text : Dict[int,str] = {}
    
    for (student_id, student_submission) in self.get_student_submissions(canvas_assignment):
      log.debug(f"Parsing student: \"{student_id}\"")
      
      for q_number, r in enumerate(student_submission):
        # log.debug(f"r: {r}")
        question_id = r["question_id"]
        if question_id not in question_text:
          question_text[question_id] = f"{h.handle(quiz.get_question(question_id).question_text)} (Max: {quiz.get_question(question_id).points_possible} points)"
        question_responses[q_number].append(question.Response_fromCanvas(student_id, question_text[question_id], h.handle(r["text"]), r["question_id"]))
    
    # Make questions from each response
    questions = [
      question.Question(question_number, responses)
      for (question_number, responses) in question_responses.items()
    ]
    
    super().__init__(questions)
    
  def push_to_canvas(self, canvas_course : canvasapi.canvas.Course, canvas_quiz_id: int):
  
    
    quiz = canvas_course.get_quiz(87942)
    
    submissions : List[canvasapi.quiz.QuizSubmission] = quiz.get_submissions()
    
    for submission in submissions:
      student_id = submission.user_id
      quiz_submission_questions : List[canvasapi.quiz.QuizSubmissionQuestion] = submission.get_submission_questions()
      
      student_responses = [
        r for q in self.questions
        for r in q.responses
        if r.student_id == student_id
      ]
      
      updated_quiz = submission.update_score_and_comments(quiz_submissions=[
        {
          'attempt': 1,
          'fudge_points': "null",
          'questions': {
            f"{question.id}": {
              'score': student_responses[i].score,
              'comment': student_responses[i].feedback if student_responses[i].feedback is not None else ""
            }
            for i, question in enumerate(quiz_submission_questions)
          }
        }
      ])



class CanvasProgrammingAssignment(CanvasAssignment):
  def __init__(self, course_id : int, assignment_id : int, prod=False):
    # Set up canvas course information
    
    self.submission_files = collections.defaultdict(list)
    
    # todo: There's not a great parallel between assignments and quizzes with questions
    #   I think that means I'll need to refactor to have things be question-based and submission-based
    #   Although a per-function thing could in fact be submission based, but for right now I'm going
    #   to just declare them "the same but different" and assume I'm doing things semi-manually
    #   until I have time for a refactor
    super().__init__(course_id, assignment_id, prod)
    self.needs_grading = True
  
  
  def prepare_assignment_for_grading(self, limit=None, regrade=False):
    
    # Grab assignment contents
    assignment_submissions : List[canvasapi.assignment.Submission] = self.get_student_submissions(self.canvas_assignment, True)
    log.debug(f"# assignment_submissions: {len(assignment_submissions)}")
    
    if regrade:
      ungraded_submissions = assignment_submissions
    else:
      ungraded_submissions = list(filter(lambda s: s.workflow_state == "submitted", assignment_submissions))
    
    if limit is not None:
      ungraded_submissions = ungraded_submissions[:limit]
    
    self.needs_grading = len(list(ungraded_submissions)) != 0
    
    log.debug(f"# ungraded_submissions: {len(ungraded_submissions)}")
    
    self.submission_files = self.download_submission_files(ungraded_submissions)
    
  
  def grade(self, grader: grader_module.Grader, push_feedback=False):
    for (user_id, attempt_number), files in self.submission_files.items():
      log.debug(f"grading ({user_id}) : {files}")
      try:
        submission = self.canvas_assignment.get_submission(user_id)
      except requests.exceptions.ConnectionError as e:
        log.error(e)
        log.debug(f"Failed on user_id = {user_id})")
        log.debug(f"username: {self.canvas_course.get_user(user_id)}")
        continue
      
      # Grade submission
      feedback: misc.Feedback = grader.grade_assignment(input_files=files)
      # log.debug(f"feedback: {feedback}")
      # log.debug(f"overall_feedback: \n{feedback.overall_feedback}")
      
      # log.debug(f"Preparing feedback for: {user_id}")
      
      # todo: combine all of this somehow more elegantly
      with io.FileIO("feedback.txt", 'w+') as ffid:
        ffid.write(feedback.overall_feedback.encode('utf-8'))
        ffid.flush()
        ffid.seek(0)
        if push_feedback:
          submission.upload_comment(ffid)
      if push_feedback:
        os.remove("feedback.txt")
      
      # Push feedback to canvas
      if push_feedback:
        submission.edit(
          submission={
            'posted_grade':feedback.overall_score,
          },
          # comment={
          #   'text_comment': feedback.overall_feedback
          # }
        )
      
    