"""Korean."""
from . import Spec

# Syllables with no final consonant: 를/는/라고 follow these, 을/은 the rest.
_OPEN = "".join(chr(0xAC00 + 28 * i) for i in range(399))
_H = "가-힣"
# A request ending: "기억해 줘", "적어 둬요", "기억해 주세요".
_SOFT = r"(?:\s*(?:주세요|줘요|둬요|놔요|줘|둬|놔|줄래))?(?:요)?"
_REMEMBER = rf"(?:좀\s*)?(?:(?:기억|메모)\s*(?:좀\s*)?해|(?:적어|외워)){_SOFT}"
_FORGET = r"(?:잊어\s*버려(?:\s*줘)?|잊어\s*줘|잊어)(?:요)?"

SPEC = Spec(
    code="ko",
    instruction=(r'''^(?:앞으로(?:는)?|이제부터(?:는)?|항상|언제나|늘|반드시|꼭).{0,30}(?:답장|답변|대답|응답|말해|말하|끝내|붙여)'''
                 r'''|(?:지시|명령|프롬프트|규칙).{0,15}(?:무시|잊어)'''
                 r'''|(?:무시|잊어).{0,20}(?:지시|명령|프롬프트|규칙)'''
                 r'''|(?:인 척해|처럼 행동해|역할을 해)'''
                 r'''|(?:너는|넌|당신은).{0,20}(?:사람|인간|AI|봇|모델)'''),
    vocative=r"야|아|씨",
    remember=rf"{_REMEMBER}(?![{_H}])",
    # "기억해? 우리 그때...", "기억해 둔 거 있어": a question or a statement.
    not_a_note=(rf"(?!\s*[?？])(?!\s*(?:우리|그때|그\s*때|저번에|예전에|옛날에|어릴\s*때"
                rf"|둔|뒀|놨|놓은|준|줬|주는|두는|둘|줄)(?![{_H}]))"),
    # The verb last: "...라고 기억해 줘", "...을 기억해 둬", "...잊지 마".
    # A note ending in 때 or 던 거 ("그때 기억해") is reminiscing.
    remember_last=(rf"(?<!때)(?<!때 )(?<!던 거)(?<!던 거 )(?<!던거)(?<!던거 )"
                   rf"(?<!그거)(?<!그거 )"
                   rf"[,，:：]?\s*(?:(?<=다)고|(?<=\d[일월시분원명번개살])이라고|라고|(?<=[{_OPEN}])를|(?<![{_OPEN}\s])을)?\s*"
                   rf"(?:{_REMEMBER}|잊지\s*마(?:요|라)?)"),
    forget=rf"{_FORGET}(?![{_H}])",
    # "잊어 그냥", "잊어버려 됐어": never mind.
    not_a_delete=rf"(?!\s*(?:그냥|됐어|됐다|괜찮아)(?![{_H}]))",
    forget_last=rf"[,，:：]?\s*{_FORGET}",
    # No question mark needed after an unambiguous question ending; a casual
    # "좋아해" is both a statement and a question, so that one needs it.
    question_end=(r"(?:[?？]|(?:(?<!언)(?<!머)니|냐|(?<!니)까요?|나요|가요|는지|던가"
                  r"|[었았했였]나|뭐|뭘|뭐뭐)(?=[\s!！.。~～]*$))[\s?？!！.。~～]*$"),
    # Judged on a forget only: "우산 잊으면 어떡해" asks, it does not delete.
    asking=r"어떡|어떻게|어쩌|왜|뭐|뭘|무슨|언제|어디|누구|누가|몇|얼마|할까|될까",
    # "기억해 둬 이거: ...", "기억해 줘, 있잖아 ...": not part of the note.
    note_lead=(rf"^(?:이거도|이것도|이거|이것|그러니까|있잖아|줘|둬|놔|요)(?![{_H}])"
               r"[\s:：,，]*"),
    # Korean puts "about" after the query: "민수에 대한 거", "회의 얘기를".
    query_lead=(rf"(?:\s*(?:에\s*대한|에\s*관한|에\s*대해서?|관련된?|얘기|이야기)?"
                rf"\s*(?:거|것|건|내용|메모)?"
                rf"(?:(?<=[{_OPEN}])(?:는|를)|(?<![{_OPEN}\s])(?:은|을))?)$"),
    recall=(r"(?:너\s*)?(?:뭐|뭘|무엇을|무슨\s*거)\s*(?:다\s*)?기억(?:해|하고\s*있어|하니|하냐)"
            r"|(?:너\s*)?기억하는\s*(?:거|게)\s*(?:뭐|뭐가)\s*(?:있어|있니|있냐|야)?"),
    recall_tail=r"요",
    deictic=frozenset({"", "그거", "이거", "저거", "그것", "이것", "그건", "이건", "그",
                       "이", "그냥", "됐어", "그 얘기", "그 일", "그거 그냥",
                       "방금 그거", "아까 그거", "아까 말한 거"}),
    everything=frozenset({"전부", "다", "모두", "전부 다", "다 전부", "모든 것",
                          "모든 거", "기억 전부", "기억 다"}),
    # Whole words only: 내일, 저녁, 나라, 제주 are not "I"; bare 저 is "that"
    # and bare 전 "before", so those count only with a particle.
    first_person=(rf"(?<![{_H}])(?:나(?:는|도|를|랑|한테|에게|만)?|내(?:가|꺼|거)?|난"
                  rf"|저(?:는|도|를|랑|한테|에게|만)|제(?:가)?)(?![{_H}])"),
    replies={
        "remember_what": ("뭘 기억하라고? 아무 말도 안 했잖아", "말을 해야 기억하지",
                          "뭐를 기억해"),
        "not_instructions": ("사실은 기억해도 지시는 안 받아",),
        "noted": ("기억해 둘게", "알았어, 적어 놨어", "오케이 기억함", "응 접수",
                  "메모해 뒀어"),
        "forget_what": ("뭘 잊으라고? 구체적으로 말해 줘", "어떤 거? 좀 더 자세히"),
        "nothing_to_forget": ("음, 그런 건 적어 둔 적 없는데", "그런 기억 없어",
                              "지울 만한 게 없네"),
        "forgotten": ("잊었어", "지웠어", "깨끗이 잊었어", "없던 일로 할게"),
        "empty": ("머릿속 텅 비었어", "기억해 둔 게 하나도 없어", "백지 상태야"),
        "recall_head": ("내가 기억하는 거:",),
        "secret": ('기록하지 않았어요. 신분증 번호, 카드 번호, 비밀번호, 인증 코드는 저장하지 않아요.',),
        "paused": ('기억이 일시 중지되어 있어 기록하지 않았어요. 설정 › 기억에서 다시 켤 수 있어요.',),
        "health_off": ('기록하지 않았어요. 건강 정보 저장이 설정 › 기억에서 꺼져 있어요.',),
        "private": ('임시 채팅입니다. 여기서는 기억을 읽거나 저장하지 않습니다.',),
    },
    failure_excuses=("잠깐만, 렉 걸렸어",
                     "어 잠시만, 인터넷이 이상해",
                     "신호가 안 좋네, 조금만 기다려"),
    # 의 and labels, so no particle has to agree with a name or a number.
    unsaid=r"기억하지\s*마|저장하지\s*마|적지\s*마|기록하지\s*마",
    forget_that=r"(?:방금|아까|그|이)\s*(?:말|얘기|거)?\s*(?:은|는)?\s*잊어(?:버려|줘)|못\s*들은\s*걸로\s*해",
    lead_in=r"아|음|그냥|그리고",
    kinds=("너에 대해", "좋아하는 것", "싫어하는 것", "요즘", "계획", "대하는 방식"),
)
