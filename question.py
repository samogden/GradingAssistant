#!env python
from __future__ import annotations

import abc
import base64
import io
import itertools
import json
import logging
import os
import random
import threading
import time
from pprint import pprint
from typing import List, Dict

import PIL.Image
import pymupdf as fitz
import requests

import tkinter as tk
from tkinter import scrolledtext

from openai import OpenAI


# from assignment import QuestionLocation

logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

class Question:
  def __init__(self, question_number, responses : List[Response], max_points = 0):
    self.question_number = question_number
    self.responses : List[Response] = responses
    self.max_points = max_points
  
  def __str__(self):
    return f"Question({self.question_number}, {len(self.responses)})"
  
  
  def get_tkinter_frame(self, parent, callback=(lambda : None)) -> tk.Frame:
    frame = tk.Frame(parent)
    
    # Make a scrollbar for the Listbox
    question_scrollbar = tk.Scrollbar(frame)
    question_scrollbar.pack(side=tk.RIGHT, fill=tk.BOTH)
    
    # Make a Listbox for questions
    response_listbox = tk.Listbox(frame, yscrollcommand=question_scrollbar.set)
    def redraw_responses():
      callback() # todo make this propagate better?
      response_listbox.delete(0, tk.END)
      for i, r in enumerate(self.responses):
        response_listbox.insert(i, f"{'ungraded' if r.score is None else 'graded'}")
    redraw_responses()
    response_listbox.pack()
    response_listbox.focus()
    
    def doubleclick_callback(_):
      
      response_window = tk.Toplevel(parent)
      response_frame = tk.Frame(response_window)
      response_frame.pack()
      
      
      def submit_callback():
        replace_response_frame(response_frame)
        redraw_responses()
        
      def show_response(response, parent):
        question_frame = response.get_tkinter_frame(parent, callback=submit_callback)
        question_frame.pack()
        
      def replace_response_frame(response_frame):
        # get rid of the old response frame and all its children
        response_frame.destroy()
        
        # See what responses are available (i.e. not yet graded)
        possible_responses = list(filter(
          lambda r: r.score is None,
          self.responses
        ))
        # If there are no ungraded responses then close the window
        if len(possible_responses) == 0:
          response_window.destroy()
          return
        
        
        # Otherwise, pick a response and rebuild the frame
        next_response = random.choice(possible_responses)
        response_frame = tk.Frame(response_window)
        response_frame.pack()
        show_response(next_response, response_frame)
      
      
      response_idx = response_listbox.curselection()[0]
      selected_response = self.responses[response_idx]
      show_response(selected_response, response_frame)
      return
    
    # Set up a callback for double-clicking
    response_listbox.bind('<Double-1>', doubleclick_callback)
    
    frame.pack()
    return frame


class Response(abc.ABC):
  """
  Class for containing student responses to a question
  """
  def __init__(self, student_id):
    self.student_id = student_id
    
    # Things that we'll get from the user or from elsewhere
    self.score = None         # user/gpt
    self.feedback = None      # user
    self.student_text = None  # gpt
    self.score_gpt = None     # gpt
    self.feedback_gpt = None  # gpt
    
  def __str__(self):
    return f"Response({self.student_id}, {self.score})"
  
  @abc.abstractmethod
  def _get_student_response_for_gpt(self) -> Dict:
    pass
  
  def set_score(self, new_score):
    log.debug(f"Updating score from {self.score} to {new_score}")
    self.score = new_score
  
  def get_chat_gpt_response(self, system_prompt=None, examples=None, max_tokens=1000, fakeit=False) -> Dict:
    log.debug("Sending request to OpenAI...")
    
    messages = []
    # Add system prompt, if applicable
    if system_prompt is not None:
      messages.append(
        {
          "role": "system",
          "content": [
            {
              "type": "text",
              "text": f"{system_prompt}"
            }
          ]
        }
      )
    
    # Add in examples for few-shot learning
    if examples is not None:
      messages.extend(examples)
    
    # Add grading criteria
    messages.append(
      {
        "role": "user",
        "content": [
          {
            "type": "text",
            "text":
              "Please grade this submission for me."
              "Please give me a response in the form of a JSON dictionary with the following keys:\n"
              "possible_points : the number of points possible from the problem\n"
              "awarded_points : how many points do you award to the student's submission, and only use integer value\n"
              "student_text : all the handwritten text that the student gave as their response to the question\n"
              "explanation : why are you assigning the grade you are\n"
          },
          self._get_student_response_for_gpt()
        ]
      }
    )
    
    if not fakeit:
      client = OpenAI()
      response = client.chat.completions.create(
        model="gpt-4o",
        response_format={ "type": "json_object"},
        messages=messages,
        temperature=1,
        max_tokens=max_tokens,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0
      )
      
      return json.loads(response.choices[0].message.content)
    else:
      time.sleep(1)
      return {
        'awarded points': 8,
        'explanation': 'This is a fake explanation',
        'possible points': 8,
        'student text': 'text that the student said'
        }
  
  
  def update_from_gpt(self, callback_func=(lambda : None), ignore_existing=False, fakeit=False):
    if (self.feedback_gpt is not None) and (not ignore_existing):
      # Then we can assume it's already been run or started so we should skip
      callback_func()
      return
    response = self.get_chat_gpt_response(fakeit=fakeit)
    log.debug(f"response: {response}")
    if "student text" in response:
      self.student_text = response["student text"]
    else:
      self.student_text = response["student_text"]
    self.feedback_gpt = response["explanation"]
    if "awarded points" in response:
      self.score_gpt = response["awarded points"]
    else:
      self.score_gpt = response["awarded_points"]
    
    callback_func()


class Response_fromPDF(Response):
  def __init__(self, student_id, img: PIL.Image.Image):
    super().__init__(student_id)
    self.img : PIL.Image.Image = img
  
  @classmethod
  def load_from_pdf(cls, student_id, path_to_pdf, question_locations, question_margin=10) -> Dict[int,Response]:
    pdf_doc = fitz.open(path_to_pdf)
    responses: Dict[int,Response] = {}
    for (page_number, page) in enumerate(pdf_doc.pages()):
      
      # Find the size of the page so we can take a slice out of it
      page_width = page.rect.width
      page_height = page.rect.height
      
      # Filter out to only the questions that are on the current page
      questions_on_page = list(filter((lambda ql: ql.page_number == page_number), question_locations))
      
      # Walk through all the questions one and grab pictures out
      for (q_start, q_end) in zip(questions_on_page, questions_on_page[1:] + [None]):
        if q_end is None:
          question_rect = fitz.Rect(0, q_start.location - question_margin, page_width, page_height)
        else:
          question_rect = fitz.Rect(0, q_start.location, page_width - question_margin, q_end.location + question_margin)
        question_pixmap = page.get_pixmap(matrix=fitz.Matrix(1, 1), clip=question_rect)
        responses[q_start.question_number] = cls(
          student_id,
          PIL.Image.open(io.BytesIO(question_pixmap.tobytes()))
        )
      
    return responses
  
  def get_b64(self, format="PNG"):
    # Create a BytesIO buffer to hold the image data
    buffered = io.BytesIO()
    
    # Save the image to the buffer in the specified format
    self.img.save(buffered, format=format)
    
    # Get the byte data from the buffer
    img_byte = buffered.getvalue()
    
    # Encode the byte data to base64
    img_base64 = base64.b64encode(img_byte)
    
    # Convert the base64 byte data to a string
    img_base64_str = img_base64.decode('utf-8')
    
    return img_base64_str
  
  def _get_student_response_for_gpt(self):
    return {
      "type": "image_url",
      "image_url": {
        "url": f"data:image/png;base64,{self.get_b64()}"
      }
    }
  
  def get_tkinter_frame(self, parent, callback=(lambda : None)) -> tk.Frame:
    
    frame = tk.Frame(parent)
    
    # Set up the image
    self.photo = PIL.ImageTk.PhotoImage(self.img)
    self.label = tk.Label(frame, image=self.photo, compound="top")
    self.label.grid(row=0, column=0, rowspan=4)
    
    # Set up the area that will contain the returned student text
    student_text_frame = tk.Frame(frame)
    tk.Label(student_text_frame, text="Student response").pack(anchor=tk.SW)
    self.text_area_student_text = scrolledtext.ScrolledText(student_text_frame, wrap=tk.WORD, width=80)
    self.text_area_student_text.pack()
    student_text_frame.grid(row=0, column=1)
    
    # Set up the response form GPT
    explanation_frame = tk.Frame(frame)
    
    explanation_frame_gpt = tk.Frame(explanation_frame)
    tk.Label(explanation_frame_gpt, text="GPT Response").pack(anchor=tk.SW)
    self.text_area_gpt_response = scrolledtext.ScrolledText(explanation_frame_gpt, wrap=tk.WORD, width=40)
    self.text_area_gpt_response.pack()
    explanation_frame_gpt.grid(column=0, row=0)
    
    explanation_frame_feedback = tk.Frame(explanation_frame)
    tk.Label(explanation_frame_feedback, text="Feedback").pack(anchor=tk.SW)
    self.text_area_feedback = scrolledtext.ScrolledText(explanation_frame_feedback, wrap=tk.WORD, width=40)
    self.text_area_feedback.pack()
    explanation_frame_feedback.grid(column=1, row=0)
    
    explanation_frame.grid(row=1, column=1)
    
    # Set up the place to enter the score for the submission
    def on_submit():
      self.set_score(int(self.score_box.get(1.0, 'end-1c')))
      self.feedback = self.text_area_feedback.get(1.0, 'end-1c')
      parent.destroy()
      callback()
    score_frame = tk.Frame(frame)
    tk.Label(score_frame, text="Score").grid(row=0, column=0)
    self.score_box = tk.Text(score_frame, height=1, width=4)
    self.score_box.grid(row=0, column=1)
    self.submit_button = tk.Button(score_frame, text="Submit", command=on_submit)
    self.submit_button.grid(row=0, column=2)
    score_frame.grid(row=2, column=1)
    
    def update_after_gpt_completion():
      log.debug("Updating after completion")

      def replace_text_area(text_area, new_text):
        text_area.delete('1.0', tk.END)
        text_area.insert(tk.END, new_text)
      # self.text_area_gpt_response.
      replace_text_area(self.text_area_gpt_response, self.feedback_gpt)
      replace_text_area(self.text_area_student_text, self.student_text)
      if self.score is not None:
        replace_text_area(self.score_box, self.score)
      else:
        replace_text_area(self.score_box, self.score_gpt)


    threading.Thread(
      target=self.update_from_gpt,
      kwargs={
        "callback_func" : update_after_gpt_completion,
        "fakeit" : False
      }
    ).start()
    # self.update_from_gpt(callback_func=update_after_completion, fakeit=True)
    
    
    return frame