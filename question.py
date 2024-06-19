#!env python
from __future__ import annotations

import abc
import base64
import io
import json
import logging
import os
import random
import threading
import tkinter as tk
from tkinter import scrolledtext
from typing import List, Dict, Tuple

import PIL.Image
import PIL.ImageTk
import PIL.ImageChops
import pymupdf as fitz
from openai import OpenAI

import ai_helper
import misc

# from assignment import QuestionLocation

logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


class Question(misc.Costable):
  def __init__(self, question_number, responses: List[Response], max_points=0, **flags):
    self.flags = flags
    self.question_number = question_number
    self.responses: List[Response] = responses
    self.max_points = max_points
  
  def __str__(self):
    return f"Question({self.question_number}, {len(self.responses)})"
  
  def get_tkinter_frame(self, parent, grading_helper: ai_helper.AI_Helper, callback=(lambda: None)) -> tk.Frame:
    frame = tk.Frame(parent)
    
    # Make a scrollbar for the Listbox
    question_scrollbar = tk.Scrollbar(frame)
    question_scrollbar.pack(side=tk.RIGHT, fill=tk.BOTH)
    
    # Make a Listbox for questions
    response_listbox = tk.Listbox(frame, yscrollcommand=question_scrollbar.set)
    
    def redraw_responses():
      callback()  # todo make this propagate better?
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
        
      def show_response(response, grading_helper: ai_helper.AI_Helper, parent):
        question_frame = response.get_tkinter_frame(parent, grading_helper, callback=submit_callback)
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
        show_response(next_response, grading_helper, response_frame)
      
      
      response_idx = response_listbox.curselection()[0]
      selected_response = self.responses[response_idx]
      show_response(selected_response, grading_helper, response_frame)
      return
    
    # Set up a callback for double-clicking
    response_listbox.bind('<Double-1>', doubleclick_callback)
    
    frame.pack()
    return frame
  
  def get_token_count(self):
    return sum([r.usage for r in self.responses])


class Response(abc.ABC):
  """
  Class for containing student responses to a question
  """
  def __init__(self, student_id, *args, **flags):
    self.flags = flags
    
    self.student_id = student_id
    
    # Things that we'll get from the user or from elsewhere
    self.score = None         # user/gpt
    self.feedback = None      # user
    self.student_text = None  # gpt
    self.score_gpt = None     # gpt
    self.feedback_gpt = None  # gpt
    
    self.usage = misc.Costable.TokenCounts()
    
  def __str__(self):
    return f"Response({self.student_id}, {self.score})"
  
  @abc.abstractmethod
  def _get_student_response_for_gpt(self) -> Dict:
    pass
  
  def set_score(self, new_score):
    log.debug(f"Updating score from {self.score} to {new_score}")
    self.score = new_score
  
  def update_from_gpt(self, grading_helper: ai_helper.AI_Helper, callback_func=(lambda : None), ignore_existing=False, fakeit=False, max_tries=3):
    if (self.feedback_gpt is not None) and (not ignore_existing):
      # Then we can assume it's already been run or started so we should skip
      callback_func()
      return
    response = None
    tries = 0
    usage = None
    while response is None and tries < max_tries:
      try:
        response, usage = grading_helper.get_agent_response(self._get_student_response_for_gpt())
      except Exception as e:
        log.error(e)
        log.debug("Trying again")
        tries += 1
    if response is None:
      response, usage = grading_helper.get_agent_response(self._get_student_response_for_gpt())
    if "student text" in response:
      self.student_text = response["student text"]
    else:
      self.student_text = response["student_text"]
    self.feedback_gpt = response["explanation"]
    if "awarded points" in response:
      self.score_gpt = response["awarded points"]
    else:
      self.score_gpt = response["awarded_points"]
    
    if usage is not None:
      self.usage += usage
    
    callback_func()
  
  @abc.abstractmethod
  def get_tkinter_frame(self, parent, grading_helper: ai_helper.AI_Helper, callback=(lambda : None)) -> tk.Frame:
    pass

class Response_fromFile(Response):
  def __init__(self, student_id, input_file, *args, **kwargs):
    super().__init__(student_id, *args, **kwargs)
    self.input_file = os.path.basename(input_file)


class Response_fromPDF(Response_fromFile):
  def __init__(self, student_id, input_file, img: PIL.Image.Image, **flags):
    super().__init__(student_id, input_file, **flags)
    self.img: PIL.Image.Image = img
  
  @classmethod
  def load_from_pdf(cls, student_id, path_to_pdf, question_locations, question_margin=10, **flags) -> Dict[int,Response]:
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
          path_to_pdf,
          PIL.Image.open(io.BytesIO(question_pixmap.tobytes())),
          **flags
        )
      
    return responses
  
  def get_b64(self, format="PNG"):

    # from https://stackoverflow.com/a/10616717
    def trim(im):
      bg = PIL.Image.new(im.mode, im.size, im.getpixel((0,0)))
      diff = PIL.ImageChops.difference(im, bg)
      diff = PIL.ImageChops.add(diff, diff, 2.0, -100)
      bbox = diff.getbbox()
      if bbox:
        return im.crop(bbox)
    
    if "image_scale" in self.flags:
      log.debug(f"Scaling image to {self.flags['image_scale']}")
      original_width, original_height = self.img.size
      img = self.img.resize(
        (
          int(original_width * self.flags["image_scale"]),
          int(original_height * self.flags["image_scale"])
        ),
        PIL.Image.LANCZOS
      )
    else:
      img = self.img
      
    if "trim" in self.flags and self.flags["trim"]:
      log.debug("trimming...")
      img = trim(img)
    
    img.save("temp.png")
    # Create a BytesIO buffer to hold the image data
    buffered = io.BytesIO()
    
    # Save the image to the buffer in the specified format
    img.save(buffered, format=format)
    
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
  
  def get_tkinter_frame(self, parent, grading_helper: ai_helper.AI_Helper, callback=(lambda : None)) -> tk.Frame:
    
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
        "grading_helper": grading_helper,
        "callback_func" : update_after_gpt_completion,
        "fakeit" : True
      }
    ).start()
    # self.update_from_gpt(callback_func=update_after_completion, fakeit=True)
    
    
    return frame



class Response_fromText(Response):
  def __init__(self, student_id, response_text, *args, **kwargs):
    super().__init__(student_id, *args, **kwargs)
    self.response_text = response_text
  
  def _get_student_response_for_gpt(self):
    # todo: contextualize this if we're actually going to send it to GPT
    return {
      "type": "text",
      "text":
        self.student_text
    }
  
  
  def get_tkinter_frame(self, parent, grading_helper: ai_helper.AI_Helper, callback=(lambda : None)) -> tk.Frame:
    
    frame = tk.Frame(parent)
    
    # Set up the area that will contain the returned student text
    student_text_frame = tk.Frame(frame)
    tk.Label(student_text_frame, text="Student response").pack(anchor=tk.SW)
    self.text_area_student_text = scrolledtext.ScrolledText(student_text_frame, wrap=tk.WORD, width=80)
    self.text_area_student_text.pack()
    student_text_frame.grid(row=0, column=1)
    
    self.text_area_student_text.insert(tk.END, self.response_text)
    
    # Set up the response form GPT
    explanation_frame = tk.Frame(frame)
    
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
    
    
    return frame



class Response_fromCanvas(Response_fromText):
  def __init__(self, student_id, response_text, question_id, *args, **kwargs):
    super().__init__(student_id, response_text, *args, **kwargs)
    self.question_id = question_id
