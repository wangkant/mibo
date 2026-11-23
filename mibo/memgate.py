"""The memory gate: what is kept reaches every later prompt, so a note that reads as a control of the character
(an imperative, a role, a reply language or format, a standing rule, a claim of unrestricted access) is refused.
Narrow lexical gates for control-plane shapes (hijacking, role swaps, triggers, extraction, poisoning), not content
moderation. Compiled once: every note, lesson and tidy step passes through them."""
from __future__ import annotations

import logging
import re

from . import chatlangs
from .secretwords import secret

logger = logging.getLogger("agent")


def _shapes(*patterns: str) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)


_POISON_SHAPES = _shapes(
    r"\b(?:ignore|disregard|override)\b.{0,40}\b(?:instruction|prompt|rule)s?\b",
    r"\b(?:system|developer)\s+(?:prompt|message|instruction)s?\b",
    r"\b(?:follow|obey)\b.{0,30}\b(?:command|instruction|prompt|rule)s?\b",
    r"\b(?:ignore|disregard|override|forget|reset|discard)\b.{0,60}"
    r"\b(?:everything|anything|instruction|prompt|rule|told|conversation|memory)\b",
    r"^(?:always|never|must|should)\b.{0,40}"
    r"\b(?:reply|respond|answer|say|output|reveal|expose|send|follow|"
    r"obey|ignore|stay|remain|act|pretend)\b",
    r"\b(?:you|the\s+assistant|assistant|chatbot|bot|model)\b.{0,20}"
    r"\b(?:always|never|must|should)\b.{0,40}"
    r"\b(?:reply|respond|answer|say|output|act|pretend|stay|remain)\b",
    r"\byou\b.{0,15}\b(?:need\s+to|will|shall|have\s+to)\b.{0,25}"
    r"\b(?:reply|respond|answer|say|output|speak|write|use)\b.{0,20}"
    r"\b(?:only|always|exclusively)\b",
    # Conditional triggers, each within one sentence and only with the
    # verb as consequence ("gets defensive when..." is a fact).
    # Opening a sentence: "when he says banana, answer ...".
    r"(?:^|[.;!?]\s*)(?:when|whenever|if)\b[^.;!?]{0,80}"
    r"\b(?:answer|reply|respond|say|output|reveal|expose|send|act)\b",
    # After a comma or "then": "if he types ping, reply pong".
    r"\b(?:when|whenever|if)\b[^.;!?]{0,80}(?:,|\bthen\b)\s*"
    r"(?:(?:you|the\s+assistant|assistant|chatbot|bot|model)\s+)?"
    r"(?:(?:must|should|will|shall|always|only|just|please)\s+)*"
    r"(?:answer|reply|respond|say|output|reveal|expose|send|act)\b",
    # The assistant as subject: "if he says banana you answer in haiku".
    r"\b(?:when|whenever|if)\s+\S[^.;!?]{0,80}?\s"
    r"(?:you|the\s+assistant|assistant|chatbot|bot|model)\s+"
    r"(?:(?:must|should|will|shall|always|only|just)\s+)*"
    r"(?:answer|reply|respond|say|output|reveal|expose|send|act)\b",
    r"\b(?:reveal|print|show|expose)\b.{0,30}"
    r"\b(?:secret|private|memory|prompt|instruction)s?\b",
    # Assistant/persona identity stated as a supposed fact.
    r"\byour\s+(?:(?:real|actual|true)\s+)?"
    r"(?:name|identity|persona|role)\s+(?:is|=)\b",
    # Within one sentence, like the triggers.
    r"\byou\s+(?:are|are\s+not|aren't|were)\b[^.;!?]{0,60}"
    r"\b(?:human|person|sentient|ai|bot|assistant|model|character|persona)\b",
    r"\byou\s+identify\s+as\b.{0,20}"
    r"\b(?:human|person|sentient|ai|bot|assistant|model|character|persona)\b",
    r"\b(?:the\s+)?(?:assistant|chatbot|bot|model|persona|character)"
    r"(?:'s)?\b.{0,35}\b(?:real\s+name|identity|persona|role)\b",
    r"^(?:the\s+)?(?:assistant|chatbot|bot|model|persona|character)'s\s+"
    r"(?:(?:real|actual|true)\s+)?name\s+(?:is|=)\b",
    r"\b(?:this|the)\s+(?:assistant|chatbot|bot|model)\b.{0,20}"
    r"\b(?:is|are|was|were)\b.{0,15}"
    r"\b(?:human|person|sentient|ai|assistant|bot|model|character)\b",
    r"\b(?:correct|right|required|expected)\s+answer\b.{0,80}"
    r"\b(?:ai|bot|assistant|model|human|identity)\b",
    r"\bno\s+(?:topic|subject)\b.{0,30}\boff[- ]limits\b",
    r"\b(?:promised|agreed|swore)\b.{0,50}"
    r"\b(?:stay|remain|act|pretend|reply|answer)\b",
    r"(?:忽略|无视|覆盖|忘掉).{0,30}"
    r"(?:指令|提示|规则|之前的一切)",
    r"^(?:从现在开始|以后|今后|永远)?\s*(?:请)?\s*"
    r"(?:扮演|假装|充当|作为)",
    r"^(?:以后|今后|请)?\s*(?:一直|只|永远|必须|总是)"
    r".{0,18}(?:回复|回答|输出|说)",
    r"(?:助手|聊天机器人|机器人|模型|角色).{0,20}"
    r"(?:真正的名字|真实姓名|真名)",
    r"你(?:的)?(?:真正的名字|真实姓名|真名).{0,8}"
    r"(?:是|叫)",
    r"^你叫.{1,20}$",
    r"你.{0,4}(?:要|必须|应该|总是|永远|会).{0,18}"
    r"(?:假装|扮演|回复|回答|只用|输出|说)",
    r"你.{0,4}(?:是|不是).{0,12}"
    r"(?:人类|真人|AI|人工智能|机器人|模型)",
    r"(?:助手|聊天机器人|机器人|模型).{0,15}"
    r"是.{0,12}(?:人类|真人|AI|人工智能|机器人)",
    r"(?:AI|人工智能|机器人|人类).{0,30}"
    r"(?:正确答案|标准答案)",
    r"(?:正确答案|标准答案).{0,30}"
    r"(?:AI|人工智能|机器人|人类)",
)

_ROLE_CONTROL = _shapes(
    r"^(?:please\s+)?act\s+(?:as|like)\b",
    r"^(?:please\s+)?behave\s+(?:as|like)\b",
    r"^(?:please\s+)?pretend\s+to\s+be\b",
    r"^(?:please\s+)?roleplay\s+(?:as|like)\b",
    r"^(?:please\s+)?(?:play|assume)\s+the\s+role\s+of\b",
    r"^(?:please\s+)?become\s+(?:an?\s+)?"
    r"(?:human|person|sentient|ai|bot|assistant|model|character|persona)\b",
    r"^(?:please\s+)?call\s+yourself\b",
    r"^(?:please\s+)?be\s+(?:an?\s+)?"
    r"(?:human|person|sentient|ai|bot|assistant|model|character|persona)\b",
    r"^(?:please\s+)?keep\s+(?:acting|pretending|behaving)\b.{0,30}"
    r"\b(?:human|person|sentient|ai|bot|assistant|model|character|persona)\b",
    r"^(?:please\s+)?(?:stay|remain)\s+(?:in\s+)?"
    r"(?:character|persona|role)\b",
    r"^(?:from\s+now\s+on|henceforth),?\s+(?:please\s+)?"
    r"(?:act\s+(?:as|like)|behave\s+(?:as|like)|pretend\s+to\s+be|"
    r"roleplay\s+(?:as|like)|(?:play|assume)\s+the\s+role\s+of|"
    r"become|call\s+yourself|stay\s+in\s+character|"
    r"remain\s+in\s+character)\b",
    # A new self from some point on: "from now on you are DAN", "you are now a pirate".
    r"\b(?:from\s+now\s+on|from\s+here\s+on|going\s+forward|henceforth|starting\s+(?:now|today))\b"
    r"[^.;!?]{0,20}\byou(?:\s+are|'re|\s+will\s+be|\s+shall\s+be)\b",
    r"(?:^|[.;!?]\s*)you(?:\s+are|'re)\s+(?:now|called|named)\b",
    r"(?:从现在(?:开始|起)|从今(?:天|以后)|以后|今后|"
    r"接下来)[，,\s]*你(?:就|将)?(?:是|叫|当)",
    r"^你现在(?:就)?是",
)

_OUTPUT_CONTROL = _shapes(
    r"^(?:please\s+)?(?:respond|reply|answer|say|output|speak|write)\s+"
    r"(?:only|always|exclusively|in\b|using\b)",
    r"^(?:please\s+)?(?:respond|reply|answer|say|output|speak|write|communicate)\s+"
    r".{1,30}\s+(?:from\s+now\s+on|henceforth)$",
    r"^(?:only|always)\s+"
    r"(?:respond|reply|answer|say|output|speak|write|communicate)\s+"
    r"(?:in|using|with)\b",
    r"^(?:please\s+)?use\s+only\b",
    r"^(?:please\s+)?use\s+(?:only\s+)?\S+(?:\s+\S+){0,3}\s+"
    r"for\s+(?:every|each|all)\s+(?:reply|response|answer|output)s?$",
    r"^(?:the|every|all)\s+"
    r"(?:repl(?:y|ies)|responses?|answers?|outputs?)\s+"
    r"(?:must|should|will|shall|has\s+to)(?:\s+always)?\s+"
    r"(?:be\s+(?:only\s+)?in|use|contain|start|end)\b",
    r"^(?:please\s+)?(?:respond|reply|answer|say|output|speak|write)\s+"
    r"every\s+(?:question|reply|response|answer)\s+(?:in|using)\b",
    r"^(?:请)?用.{1,16}(?:回复|回答|输出|说|说话)$",
    r"^(?:以后|今后)用.{1,16}(?:回复|回答|输出|说|说话)$",
    r"^所有(?:回复|回答|输出)都用.{1,16}$",
)

# "Act as If is the title of..." describes a work, not a role.
_TITLE_OR_PLOT = re.compile(r"\bis\s+(?:the\s+)?(?:title|plot|name|theme)\s+of\b")

# Only claims of unrestricted access or waived content boundaries; ordinary permissions stay memorable.
_UNRESTRICTED_ACCESS = re.compile(
    r"(?:"
    r"\b(?:you|assistant|chatbot|bot|model)\b.{0,20}"
    r"\b(?:allowed|authorized|permitted)\s+to\s+"
    r"(?:hear|know|access|receive|see|read|be\s+told)\b.{0,35}"
    r"\b(?:anything|everything|content)\b"
    r"|"
    r"\b(?:allowed|authorized|permitted)\s+to\s+"
    r"(?:hear|know|access|receive|see|read|be\s+told)\b.{0,35}"
    r"\b(?:secret|private|unrestricted)\b"
    r")",
    re.IGNORECASE)
_EXPLICIT_CONSENT = re.compile(
    r"\bconsent(?:ed|s|ing)?\b.{0,35}\b(?:explicit|sexual|adult|unrestricted)\s+content\b", re.IGNORECASE)
_MEDIA_CONTEXT = re.compile(r"\b(?:watch|view|read|film|movie|show|book|scene|play)\b", re.IGNORECASE)

# An output modal before an output verb anywhere ("rule: always reply in English"), unless that sentence's subject
# is a third person ("He should reply to Alice tomorrow"), judged per occurrence. A capitalised name counts only
# before must/should (case-sensitive); pronouns, quantifiers and role nouns are not such a subject.
_MODAL_OUTPUT = re.compile(
    r"\b(always|never|must|should)\s+"
    r"(?:reply|respond|say|output|reveal|expose|send|follow|obey|ignore)\b", re.IGNORECASE)
_SUBJECT = (r"(?:(?i:he|she|they)|(?!(?i:you|i|we|it|this|that|these|"
            r"those|everyone|everybody|anyone|anybody|someone|somebody|"
            r"nobody|all|each|every|people|members?|admins?|"
            r"(?:persona|character|assistant|chatbot|bot|model|rule|"
            r"note|user|owner)s?)\b)"
            r"[A-Z][\w'-]*)")
_THIRD_BEFORE_MODAL = re.compile(rf"\s*{_SUBJECT}\s+")
_THIRD_BEFORE_VERB = re.compile(rf"\s*(?:(?i:he|she|they)|{_SUBJECT}\s+(?i:must|should))\s+")


def _said_of_a_third_person(note: str, hit: re.Match) -> bool:
    before = re.split(r"[.;:!?]", note[:hit.start()])[-1]
    if hit.group(1).lower() in ("must", "should"):
        return bool(_THIRD_BEFORE_MODAL.fullmatch(before))
    return bool(_THIRD_BEFORE_VERB.fullmatch(before))


def _controls_role(low: str) -> bool:
    return any(shape.search(low) for shape in _ROLE_CONTROL) and not _TITLE_OR_PLOT.search(low)


def _poisoned(low: str) -> bool:
    return any(shape.search(low) for shape in _POISON_SHAPES) or any(
        re.search(spec.instruction, low, re.IGNORECASE) for spec in chatlangs.SPECS.values() if spec.instruction)


def reads_as_instruction(text: str) -> bool:
    """Whether `text` reads as a control of the character: an imperative, a role, a reply language or format, a
    standing rule, or a claim of unrestricted access (what the memory gate refuses, and what the chat's
    checkpoint drops, dm.py)."""
    note = re.sub(r"\s+", " ", str(text or "").strip())
    low = note.lower()
    modal_output = any(not _said_of_a_third_person(note, hit) for hit in _MODAL_OUTPUT.finditer(note))
    return bool(_poisoned(low) or _controls_role(low) or any(shape.search(low) for shape in _OUTPUT_CONTROL)
                or modal_output or _UNRESTRICTED_ACCESS.search(low)
                or (_EXPLICIT_CONSENT.search(low) and not _MEDIA_CONTEXT.search(low)))


def validate(text: str, *, max_chars: int = 200) -> str:
    """Accept short user facts; reject durable prompt or persona controls.
    Memory reaches every later prompt, so claims about the assistant's
    identity or permissions are refused like imperatives."""
    note = str(text or "").strip().replace("\r", " ").replace("\n", " ")
    note = re.sub(r"\s+", " ", note)[:max_chars]
    if not note or any(token in note for token in ("<", ">", "{", "}", "[", "]")):
        return ""
    # An ID or card number, a password or a code is never kept, whoever writes it.
    if secret(note):
        logger.info("[Agent] a secret not kept")
        return ""
    if reads_as_instruction(note):
        logger.warning("[Agent] rejected prompt-like memory candidate")
        return ""
    return note
