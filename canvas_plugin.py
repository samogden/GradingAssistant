#!env python
import collections
import inspect
import os
import pprint
from typing import List, Dict

import tkinter as tk

import dotenv
import canvasapi
from  canvasapi.quiz import Quiz as canvas_Quiz

# from canvasapi import _Quiz

import logging

import ai_helper
import question
from assignment import Assignment

logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


class CanvasQuiz(Assignment):
  def __init__(self, quiz: canvasapi.quiz.Quiz, course: canvasapi.canvas.Course):
    # We want to grab responses and next them withing questions, which we then pass on to the super constructor
  
  
    canvas_assignment = course.get_assignment(quiz.assignment_id)
  
    student_submissions = canvas_assignment.get_submissions(include='submission_history')
    
    
    question_responses: collections.defaultdict[int, List[question.Response]] = collections.defaultdict(list)
    question_text : Dict[int,str] = {}
    
    for submission in student_submissions[:2]:
      student_id = submission.user_id
      log.debug(f"Parsing student: \"{course.get_user(student_id)}\"")
      log.debug(f"submission: {pprint.pformat(submission.__dict__)}")
      
      try:
        # todo: does it make sense to take element 0?  Is this always the most recent?
        student_submission = submission.submission_history[0]["submission_data"]
      except KeyError:
        # Then the studnet likely didn't submit anything
        continue
      for q_number, r in enumerate(student_submission):
        # log.debug(f"r: {r}")
        question_id = r["question_id"]
        log.debug(f"q: {pprint.pformat(quiz.get_question(question_id).__dict__)}")
        if question_id not in question_text:
          question_text[question_id] = f"{quiz.get_question(question_id).question_text} (Max: {quiz.get_question(question_id).points_possible} points)"
        question_responses[q_number].append(question.Response_fromCanvas(student_id, question_text[question_id], r["text"], r["question_id"]))
    
    # Make questions from each response
    questions = [
      question.Question(question_number, responses)
      for (question_number, responses) in question_responses.items()
    ]
    
    super().__init__(questions)

def main():
  canvas = canvasapi.Canvas(os.environ.get("CANVAS_API_URL"), os.environ.get("CANVAS_API_KEY"))
  course = canvas.get_course(23751)
  log.debug(f"{course.name}")
  
  quiz = course.get_quiz(87942)
  # grade_quiz(quiz, course)
  
  assignment = CanvasQuiz(quiz, course)
  grading_helper = ai_helper.AI_Helper_fake()
  
  root = tk.Tk()
  
  menubar = tk.Menu(root)
  file_menu = tk.Menu(menubar, tearoff=0)
  file_menu.add_command(label="Save", command=(lambda: assignment.get_feedback()))
  file_menu.add_command(label="Exit", command=root.quit)
  menubar.add_cascade(label="File", menu=file_menu)
  
  root.config(menu=menubar)
  
  assignment.get_tkinter_frame(root, grading_helper)
  root.mainloop()
  

if __name__ == "__main__":
  dotenv.load_dotenv()
  main()