#!env python
import json
from typing import Tuple, Dict

from openai import OpenAI

import misc


import logging
logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

class AI_Helper(object):
  @staticmethod
  def get_agent_response(
      student_response,
      system_prompt=None,
      few_shot_learning_examples=None,
      max_response_tokens=1000,
      *args,
      **kwargs
  ) -> Tuple[Dict, misc.Costable.TokenCounts]:
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
    if few_shot_learning_examples is not None:
      messages.extend(few_shot_learning_examples)
    
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
          student_response
        ]
      }
    )
    
    client = OpenAI()
    response = client.chat.completions.create(
      model="gpt-4o",
      response_format={ "type": "json_object"},
      messages=messages,
      temperature=1,
      max_tokens=max_response_tokens,
      top_p=1,
      frequency_penalty=0,
      presence_penalty=0
    )
    
    return json.loads(response.choices[0].message.content), misc.Costable.TokenCounts(response.usage)


class AI_Helper_fake(AI_Helper):
  def get_agent_response(
      student_response,
      system_prompt=None,
      few_shot_learning_examples=None,
      max_response_tokens=1000,
      *args,
      **kwargs
  ) -> Tuple[Dict, misc.Costable.TokenCounts]:
    return {
      'awarded points': 8,
      'explanation': 'This is a fake explanation',
      'possible points': 8,
      'student text': 'text that the student said'
    }, misc.Costable.TokenCounts()




def main():
  pass

if __name__ == "__main__":
  main()