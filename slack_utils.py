from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.models.blocks import (
  RichTextBlock,
  RichTextSectionElement,
  RichTextElementParts
)

class SlackMessageBuilder:
  """
  Fluent Interface를 사용하여 Slack 메시지를 쉽게 만드는 빌더 클래스.
  """
  def __init__(self):
    self._elements = []

  def add_line(self, text: str, emoji: str = None, bold: bool = False, code: bool = False):
    """가장 간단한 형태의 한 줄을 추가합니다."""
    line_builder = self.start_line()
    if emoji:
      line_builder.with_emoji(emoji)
    line_builder.with_text(text, bold=bold, code=code).commit()
    return self

  def start_line(self):
    """
    복잡한 형식의 줄 생성을 시작합니다.
    LineBuilder 객체를 반환하며, 메서드 체이닝이 가능합니다.
    """
    return self._LineBuilder(self)

  def build(self) -> list:
    """최종적으로 Slack API가 요구하는 blocks 리스트를 생성합니다."""
    if not self._elements:
      return []
    return [RichTextBlock(elements=self._elements).to_dict()]

  class _LineBuilder:
    """SlackMessageBuilder 내부에서 한 줄(RichTextSection)을 만드는 도우미 클래스."""
    def __init__(self, message_builder):
      self._message_builder = message_builder
      self._parts = []

    def with_emoji(self, name: str):
      """줄에 이모지를 추가합니다."""
      self._parts.append(RichTextElementParts.Emoji(name=name))
      return self

    def with_text(self, text: str, bold: bool = False, code: bool = False, italic: bool = False):
      """줄에 텍스트를 추가합니다. 다양한 스타일 적용이 가능합니다."""
      style_obj = None
      if bold or code or italic:
        style_obj = RichTextElementParts.TextStyle(bold=bold, code=code, italic=italic)

      text_content = f"{text}" if self._parts else text

      self._parts.append(
          RichTextElementParts.Text(text=text_content, style=style_obj)
      )
      return self

    def commit(self):
      """
      지금까지 구성한 줄을 확정하여 부모 빌더에 추가하고,
      계속해서 메시지를 작성할 수 있도록 부모 빌더(SlackMessageBuilder)를 반환합니다.
      """
      if self._parts:
        self._message_builder._elements.append(
            RichTextSectionElement(elements=self._parts)
        )
      return self._message_builder

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
