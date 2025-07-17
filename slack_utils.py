from contextlib import contextmanager
from typing import Optional, Union, List, Dict, Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.models.blocks import (
  RichTextBlock,
  RichTextSectionElement,
  RichTextElementParts
)


class SlackMessageBuilder:
  """
  Pythonic Slack Message Builder
  """
  def __init__(self):
    self._elements = []

  def add_line(self, text: str = "", *, emoji: Optional[str] = None,
      bold: bool = False, code: bool = False, italic: bool = False) -> 'SlackMessageBuilder':
    """
    간단한 한 줄 추가 - 가장 일반적인 사용 사례

    Args:
        text: 표시할 텍스트
        emoji: 이모지 이름 (예: 'smile', 'wave')
        bold: 굵게 표시 여부
        code: 코드 스타일 표시 여부
        italic: 기울임 표시 여부
    """
    with self.line() as line:
      if emoji:
        line.emoji(emoji)
      if text:
        line.text(text, bold=bold, code=code, italic=italic)
    return self

  @contextmanager
  def line(self):
    """
    Context Manager를 사용한 줄 생성

    Usage:
        with builder.line() as line:
            line.emoji('smile').text('Hello', bold=True)
    """
    line_builder = self._LineBuilder()
    try:
      yield line_builder
    finally:
      # 자동으로 commit 처리
      if line_builder._parts:
        self._elements.append(RichTextSectionElement(elements=line_builder._parts))

  def build(self) -> List[Dict[str, Any]]:
    """Slack API가 요구하는 blocks 리스트 반환"""
    if not self._elements:
      return []
    return [RichTextBlock(elements=self._elements).to_dict()]

  # Python의 __call__ 매직 메서드를 활용한 함수형 접근
  def __call__(self, *lines: Union[str, Dict[str, Any]]) -> 'SlackMessageBuilder':
    """
    함수형 스타일로 여러 줄을 한 번에 추가

    Usage:
        builder("Hello", {"text": "World", "bold": True})
    """
    for line in lines:
      if isinstance(line, str):
        self.add_line(line)
      elif isinstance(line, dict):
        self.add_line(**line)
    return self

  class _LineBuilder:
    """내부 Line Builder - Context Manager 내에서만 사용"""

    def __init__(self):
      self._parts = []

    def emoji(self, name: str) -> '_LineBuilder':
      """이모지 추가"""
      self._parts.append(RichTextElementParts.Emoji(name=name))
      return self

    def text(self, text: str, *, bold: bool = False, code: bool = False,
        italic: bool = False) -> '_LineBuilder':
      """텍스트 추가"""
      style = None
      if bold or code or italic:
        style = RichTextElementParts.TextStyle(bold=bold, code=code, italic=italic)
      self._parts.append(RichTextElementParts.Text(text=text, style=style))
      return self

    def space(self) -> '_LineBuilder':
      """공백 추가"""
      self._parts.append(RichTextElementParts.Text(text=" "))
      return self

def send_slack_message(blocks: list, token: str, channel: str):
  """Sends a message with the given blocks to the specified Slack channel."""
  if not blocks:
    print("Message blocks are empty, nothing to send.")
    return None

  client = WebClient(token=token)
  try:
    response = client.chat_postMessage(
        channel=channel,
        blocks=blocks
    )
    return response["ts"]
  except SlackApiError as e:
    raise Exception(f"Failed to send message: {e.response['error']}")
