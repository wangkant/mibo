"""English."""
from . import Spec

# "I" or "我": the saver talking about themself. English and Chinese share it,
# so a note in either is attributed in either.
FIRST_PERSON = (r"(?<![\w'])(?:i|i'm|i've|i'd|i'll|me|my|mine|myself)(?![\w'])"
                r"|我(?!们)")

SPEC = Spec(
    code="en",
    remember=r"(?:remember|memorize)\b",
    # "remember when we...", "remember how...": reminiscing, not a note to keep.
    not_a_note=(r"(?!\s*(?:when|how|what|who|why|where|whether|if|me|"
                r"the\s+time|that\s+time)\b)"),
    forget=r"forget\b",
    # "forget it" / "forget about it" means never mind.
    not_a_delete=r"(?!\s*(?:about\s+)?it\b)",
    recall=r"what do you remember|what'?s in your memory|memory\?",
    note_lead=r"^that\s+",
    query_lead=r"^(?:about|that)\s+",
    deictic=frozenset({"that", "this", "it", "those", "these", "that one",
                       "this one"}),
    everything=frozenset({"everything", "all", "all of it", "all of that",
                          "all that", "every note"}),
    first_person=FIRST_PERSON,
    replies={
        "remember_what": ("remember what? you didn't say anything", "spill it",
                          "remember what lol"),
        "not_instructions": ("I can remember facts, not instructions",),
        "noted": ("noted", "got it, written down", "remembered"),
        "forget_what": ("forget what? be specific", "which one? say more"),
        "nothing_to_forget": ("uh, never recorded that", "no recollection of that",
                              "nothing matching to forget"),
        "forgotten": ("forgotten", "dropped", "gone"),
        "empty": ("head's empty", "nothing in there", "blank slate"),
        "recall_head": ("Here's what I remember:",),
        "secret": ('Not kept: ID numbers, card numbers, passwords and codes are never saved.',),
    },
    failure_excuses=("ugh, hanging here for a sec",
                     "hold on, connection's wonky",
                     "signal weird rn, gimme a min"),
    stopwords=frozenset({
        "the", "and", "you", "are", "is", "was", "what", "that", "this", "it",
        "to", "of", "in", "for", "on", "with", "my", "me", "we", "do", "don't",
        "can", "just", "so", "have", "how", "why", "not", "be", "your", "i'm",
        "it's", "lol", "yeah", "hey", "there", "about", "would", "will",
    }),
    unsaid=(r"\b(?:don'?t|do not|no need to)\s+(?:remember|save|store|note|keep|write down)"
            r"\s+(?:this|that|it)\b|\boff the record\b"),
    forget_that=(r"forget (?:what i (?:just )?(?:said|told you)|i (?:said|mentioned) (?:that|it|anything)"
                 r"|(?:that|this|it)(?: please)?[\s.!]*$)|pretend i (?:never|didn'?t) (?:said|say) (?:that|it|anything)"),
    lead_in=r"ok(?:ay)?|actually|never ?mind|well|oh|also|hey",
    kinds=("About you", "Likes", "Dislikes", "Lately", "Plans", "How you like to be treated"),
)
