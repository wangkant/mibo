"""Brazilian Portuguese."""
from . import Spec

SPEC = Spec(
    code="pt-BR",
    instruction=(r'''^(?:a partir de agora|de agora em diante|sempre|nunca|você deve|você tem que)\b.{0,50}\b(?:respost\w*|respond\w*|diga\w*|fale\w*|escrev\w*|termin\w*)\b'''
                 r'''|^(?:responda|termine|diga|fale|escreva)\s+(?:sempre|só|somente|apenas)\b'''
                 r'''|\b(?:ignore|esqueça)\b.{0,40}\b(?:instruç\w+|regras?|prompt)\b'''
                 r'''|^(?:finja|aja como|faça o papel)\b'''
                 r'''|\bvocê é\b.{0,40}\b(?:humano|humana|ia|bot|assistente|modelo)\b'''),
    # "anota aí", "lembra que", "lembre-se de que", "não esquece que". No
    # "grave" (English) and no "memoriza"/"memorize" (Spanish, English).
    remember=(r"(?:n[ãa]o\s+esque[cç][ae]|lembr[ae](?:-se)?|anot[ae](?:\s+a[ií])?"
              r"|guard[ae](?:\s+a[ií])?|grava(?:\s+a[ií])?)(?![\w-])"),
    # "lembra quando...", "lembra da festa", "lembra que a gente...": reminiscing.
    not_a_note=(r"(?!\s*[,:]?\s*(?:quando|como|onde|quem|qual|se|o\s+que|aquel[ae]s?"
                r"|aquilo|daquel[ae]s?|daquilo|disso|disto|de\s+mim|me|segredo|sil[êe]ncio"
                r"|(?:isso\s+)?pra\s+(?:voc[êe]|vc|ti)"
                r"|que\s+(?:a\s+gente|n[óo]s|voc[êe]|vc)|d[aoe]s?(?!\s+que\b))\b)"),
    forget=r"(?:esque[cç][ae])\b",
    # "esquece isso", "esquece aí", "esquece, deixa pra lá": never mind.
    not_a_delete=(r"(?!\s*[,.!]?\s*(?:isso|isto|aquilo(?!\s+(?:de|sobre)\b)|disso|a[ií]|l[áa]|deixa"
                  r"|pra\s+l[áa]|tudo\s+isso)\b)"),
    recall=(r"(?:o|do)\s+que\s+(?:voc[êe]|vc|tu)\s+(?:se\s+)?lembra(?:\s+de\s+mim)?"
            r"|o\s+que\s+(?:tem|t[áa])\s+na\s+(?:sua|tua)\s+mem[óo]ria"
            r"|o\s+que\s+(?:voc[êe]|vc|tu)\s+(?:guardou|anotou)"),
    recall_tail=r"a[ií]|hein|ent[ãa]o",
    # Anchored: "o que você aprendeu na escola" is chat, not the summary.
    # Questions often drop the mark and end on a tag: "né", "não é", "lembra".
    question_end=(r"[?？][\s?？!！.。~～]*$"
                  r"|\b(?:n[ée]|n[ãa]o\s+[ée]|sabe|lembra|certo|hein)[\s!.~]*$"),
    asking=r"\b(?:como|por\s*qu[eê]|pq|onde|qual|quais|quem|o\s+que|e\s+se|ser[áa]\s+que)\b",
    note_lead=(r"^(?:(?:de\s+que|que|a[ií]|isso|isto|l[áa]|pra\s+mim|por\s+favor|pfv)"
               r"(?:\s*[:,]\s*|\s+|$))+"),
    query_lead=(r"^(?:(?:o\s+lance\s+d[aoe]s?|a\s+parte\s+d[aoe]s?|aquilo\s+(?:de|sobre)"
                r"|a\s+d[aoe]s?|o\s+d[aoe]s?|sobre|d[aoe]s?|que|as|os|a|o)\s+)+"),
    deictic=frozenset({"isso", "isto", "aquilo", "disso", "disto", "daquilo",
                       "esse", "essa", "este", "esta", "isso aí", "isso ai",
                       "esse aí", "essa aí", "aquilo lá", "ele", "ela"}),
    everything=frozenset({"tudo", "tudo isso", "tudinho", "todas", "todos",
                          "tudo que você sabe", "tudo que vc sabe"}),
    first_person=r"(?<![\w'])(?:eu|me|mim|comigo|meu|meus|minha|minhas)(?![\w'])",
    replies={
        "remember_what": ("lembrar o quê? você não falou nada", "fala aí, anotar o quê",
                          "anotar o quê kkk"),
        "not_instructions": ("eu guardo fatos, não instruções",),
        "noted": ("anotado", "beleza, guardei", "tá anotado"),
        "forget_what": ("esquecer o quê? fala direito", "qual delas? explica melhor"),
        "nothing_to_forget": ("hm, nunca anotei isso", "não lembro disso não",
                              "não achei nada pra esquecer"),
        "forgotten": ("esqueci", "apagado", "já era", "foi"),
        "empty": ("cabeça vazia", "não tem nada aqui", "tudo em branco"),
        "recall_head": ("Olha o que eu lembro:",),
        "secret": ('Não guardei: números de documento e de cartão, senhas e códigos nunca são salvos.',),
        "paused": ('A memória está pausada, então não guardei. Dá para reativar em Configurações › Memória.',),
        "health_off": ('Não guardei: salvar dados de saúde está desativado em Configurações › Memória.',),
        "private": ('Esta é uma conversa temporária: aqui a memória não é lida nem guardada.',),
    },
    failure_excuses=("pera, travei aqui",
                     "calma, a conexão tá zoada",
                     "sinal ruim agora, me dá um minuto"),
    # "label: {n}" throughout, so no count needs singular or plural.
    stopwords=frozenset({
        "não", "nao", "você", "voce", "vc", "tá", "ta", "tô", "né", "pra", "tenho",
        "isso", "muito", "também", "tambem", "tbm", "agora", "aqui", "gente",
        "eu", "ela", "uma", "meu", "minha", "então", "ainda", "já", "só",
        "hoje", "amanhã", "ontem", "vou", "vai", "estou", "quero", "tudo", "kkk",
        "kkkk", "rs", "beleza", "valeu", "obrigado", "obrigada", "pq", "nem",
        "acho", "aí", "bem",
    }),
    letters="ãõ",
    unsaid=r"\bnão (?:guarda|guarde|anota|anote|lembra|lembre|salva|salve) (?:isso|disso)\b",
    # "não esquece isso" asks the opposite.
    forget_that=(r"(?<!não )(?<!nao )esque(?:ce|ça) (?:o que eu (?:disse|falei)|isso)\b"
                 r"|finge que eu não (?:disse|falei) nada"),
    lead_in=r"bom|tá|ah",
    kinds=("Sobre você", "Gosta", "Não gosta", "Ultimamente", "Planos", "Como te tratar"),
)
