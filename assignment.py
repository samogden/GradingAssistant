#!env python
from __future__ import annotations

import collections
import logging
import os
import shutil
import tkinter as tk
from typing import List, Dict

import canvasapi
import html2text
import pandas as pd
import pymupdf as fitz

import ai_helper
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


class CanvasQuiz(Assignment):
  def __init__(self, quiz: canvasapi.quiz.Quiz, course: canvasapi.canvas.Course):
    # We want to grab responses and next them withing questions, which we then pass on to the super constructor
    
    
    canvas_assignment = course.get_assignment(quiz.assignment_id)
    
    student_submissions = canvas_assignment.get_submissions(include='submission_history')
    
    h = html2text.HTML2Text()
    h.ignore_links = True
    
    question_responses: collections.defaultdict[int, List[question.Response]] = collections.defaultdict(list)
    question_text : Dict[int,str] = {}
    
    for submission in student_submissions[:2]:
      student_id = submission.user_id
      log.debug(f"Parsing student: \"{course.get_user(student_id)}\"")
      
      try:
        # todo: does it make sense to take element 0?  Is this always the most recent?
        student_submission = submission.submission_history[0]["submission_data"]
      except KeyError:
        # Then the studnet likely didn't submit anything
        continue
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
