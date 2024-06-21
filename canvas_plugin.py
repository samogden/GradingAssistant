#!env python
import logging
import os
import pprint
import tkinter as tk
from typing import List

import assignment

import canvasapi
import canvasapi.quiz
import dotenv

import ai_helper

logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


def grading_flow_test():
  canvas = canvasapi.Canvas(os.environ.get("CANVAS_API_URL"), os.environ.get("CANVAS_API_KEY"))
  course = canvas.get_course(23751)
  log.debug(f"{course.name}")
  
  quiz = course.get_quiz(87942)
  # grade_quiz(quiz, course)
  
  a = assignment.CanvasQuiz(quiz, course)
  grading_helper = ai_helper.AI_Helper_fake()
  
  a.autograde(grading_helper)
  
  a.push_to_canvas(course, 87942)

def GUI():
  canvas = canvasapi.Canvas(os.environ.get("CANVAS_API_URL"), os.environ.get("CANVAS_API_KEY"))
  course = canvas.get_course(23751)
  log.debug(f"{course.name}")
  
  quiz = course.get_quiz(87942)
  # grade_quiz(quiz, course)
  
  a = assignment.CanvasQuiz(quiz, course)
  grading_helper = ai_helper.AI_Helper_fake()
  
  root = tk.Tk()
  
  menubar = tk.Menu(root)
  file_menu = tk.Menu(menubar, tearoff=0)
  file_menu.add_command(label="Save", command=(lambda: canvas_assignment.get_feedback()))
  file_menu.add_command(label="Exit", command=root.quit)
  menubar.add_cascade(label="File", menu=file_menu)
  
  root.config(menu=menubar)
  
  canvas_assignment.get_tkinter_frame(root, grading_helper)
  root.mainloop()
  
def change_grades():
  canvas = canvasapi.Canvas(os.environ.get("CANVAS_API_URL"), os.environ.get("CANVAS_API_KEY"))
  course = canvas.get_course(23751)
  log.debug(f"{course.name}")
  
  quiz = course.get_quiz(87942)
  
  submissions : List[canvasapi.quiz.QuizSubmission] = quiz.get_submissions()
  quiz_questions : List[canvasapi.quiz.QuizQuestion] = quiz.get_questions()
  log.debug(pprint.pformat(quiz_questions[0].id))
  
  
  
  for submission in submissions:
    quiz_submission_questions : List[canvasapi.quiz.QuizSubmissionQuestion] = submission.get_submission_questions()
    
    
    log.debug(f"submission: {pprint.pformat(submission.get_submission_questions())}")
    updated_quiz = submission.update_score_and_comments(quiz_submissions=[
      {
        'attempt': 1,
        'fudge_points': "null",
        'questions': {
          # f"{question.assessment_question_id}": {
          f"{question.id}": {
            'score': 10,
            'comment': "Great job!"
          }
          for i, question in enumerate(quiz_submission_questions)
        }
      }
    ])
    log.debug(f"{pprint.pformat(updated_quiz.__dict__)}")
    # submission.complete(submission.validation_token)


def main():
  canvas = canvasapi.Canvas(os.environ.get("CANVAS_API_URL"), os.environ.get("CANVAS_API_KEY"))
  course = canvas.get_course(23751)
  log.debug(f"{course.name}")
  
  return
  
  canvas_assignment = assignment.CanvasQuiz(quiz, course)
  grading_helper = ai_helper.AI_Helper_fake()
  
  root = tk.Tk()
  
  menubar = tk.Menu(root)
  file_menu = tk.Menu(menubar, tearoff=0)
  file_menu.add_command(label="Save", command=(lambda: canvas_assignment.get_feedback()))
  file_menu.add_command(label="Exit", command=root.quit)
  menubar.add_cascade(label="File", menu=file_menu)
  
  root.config(menu=menubar)
  
  canvas_assignment.get_tkinter_frame(root, grading_helper)
  root.mainloop()
  

if __name__ == "__main__":
  dotenv.load_dotenv()
  main()