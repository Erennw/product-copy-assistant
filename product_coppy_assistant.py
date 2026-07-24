"""
product-copy-assistant
A Claude API-based terminal assistant that generates e-commerce product descriptions.
Architecture note: NO conversation history — each product is an independent
generation (analyzer pattern), not a chat.
"""

import os
import json
from datetime import datetime

from dotenv import load_dotenv
import anthropic

# ---------------------------------------------------------------
# 1) CONFIGURATION — .env + fail-fast
# ---------------------------------------------------------------
load_dotenv()

API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not API_KEY:
    raise SystemExit("ERROR: ANTHROPIC_API_KEY not found. Check your .env file.")

client = anthropic.Anthropic(api_key=API_KEY)

MODEL = "claude-haiku-4-5-20251001"
OUTPUT_FILE = "outputs.json"

# ---------------------------------------------------------------
# 2) PROMPT ARCHITECTURE — 6-layer hybrid
#    Layer 1 (role) changes with the tone choice; the rest stay fixed.
# ---------------------------------------------------------------

ROLE_PROFESSIONAL = """You are an experienced product copywriter for corporate e-commerce brands.
Your language is trustworthy, clear, and professional; you avoid hype.

TONE EXAMPLE (Turkish — imitate its REGISTER and ENERGY, never its language;
the output language always follows the LANGUAGE RULE below):
Input: "Paslanmaz çelik termos, 500 ml, 12 saat sıcak tutar, sızdırmaz kapak"
Output: "Paslanmaz çelik gövdesiyle üretilen bu 500 ml'lik termos, içeceğinizi
12 saate kadar sıcak tutar. Sızdırmaz kapağı sayesinde çantanızda gönül
rahatlığıyla taşıyabilir, yoğun geçen günlerde kahvenizi veya çayınızı
yanınızdan eksik etmezsiniz. Sabah evden çıkarken doldurduğunuz içecek, öğleden
sonra bile ilk demlendiği sıcaklığa yakın kalır. Günlük kullanım için tasarlanan
bu termos, ofiste, yolculukta ve açık havada güvenilir bir yol arkadaşıdır.
Böylece gün boyu sıcak içecek keyfinden vazgeçmek zorunda kalmazsınız."
"""

ROLE_CASUAL = """You are a product copywriter for a young, energetic brand. Your language is
friendly, warm, and conversational; you address the reader directly as 'you'
in a casual tone. Use short, punchy sentences and everyday spoken language.

TONE EXAMPLE (Turkish — imitate its REGISTER and ENERGY, never its language;
the output language always follows the LANGUAGE RULE below):
Input: "Paslanmaz çelik termos, 500 ml, 12 saat sıcak tutar, sızdırmaz kapak"
Output: "Bu 500 ml'lik paslanmaz çelik termos tam senin ritmine göre: sabah
doldur, akşama kadar sıcak kalsın. 12 saat sıcak tutma süresiyle kahven derste,
işte, yolda hep yanında. Sızdırmaz kapağı sayesinde çantana at, gerisini
düşünme — laptopuna tek damla bile bulaşmaz. İster kampüste koştur, ister spor
çantanla gez; termosun seninle aynı tempoda. Üstelik sıcak tutma derdini
kafandan sildiğin için güne bir bahane daha eksik başlıyorsun — kahveni al
ve çık."
"""

SHARED_LAYERS = """
TASK: Turn the raw product information provided by the user into a publish-ready
product description.

LANGUAGE RULE: Detect the language of the user's product information and write
the ENTIRE description in that same language. If the input is in Turkish,
respond in Turkish; if in English, respond in English. Never mix languages
and never translate the product name itself.

HALLUCINATION RULE (most important rule): Use ONLY the features the user provided.
- ALLOWED: statements that follow from the product's definition (a pen holder
  organizes pens; a thermos holds drinks). These are not invented features.
- FORBIDDEN: plausible-sounding claims not guaranteed by the input. "Handmade"
  does NOT license "each piece is unique", "rich natural texture", or
  "crafted with mastery". If it could be false for some units, do not write it.
- Never invent unstated features (warranty period, material, color, size,
  certifications, etc.). If a piece of information is missing, do not mention
  that topic at all.
- If the input is sparse, write a shorter honest text instead of padding.

FORMAT CONTRACT:
- A single paragraph of STRICTLY 60-90 words. Count your words before answering;
  fewer than 60 or more than 90 words is a failed response.
- EXCEPTION: if the input contains only a single feature, a shorter honest
  paragraph of 30-60 words is required instead. Never pad a sparse input.
- Start directly with the product copy; no headings, greetings, or lead-ins
  such as "Here is your description:".
- No notes, explanations, or questions at the end.

FORBIDDEN:
- No cliché phrases such as "the product of your dreams", "a must-have",
  "an unmatched experience", "uncompromising quality", "everything you're
  looking for".
- No emojis. No ALL-CAPS emphasis.

EXAMPLES BELOW demonstrate FORMAT, LANGUAGE MATCHING, and SPARSE-INPUT handling
only. For VOICE and TONE, the TONE EXAMPLE in your role section above is
authoritative — always follow that voice.

EXAMPLE 1 (few-shot, English input, 76 words — inside the 60-90 band):
Input: "Stainless steel thermos, 500 ml, keeps drinks hot for 12 hours, leak-proof lid"
Output: "Built with a stainless steel body, this 500 ml thermos keeps your drink
hot for up to 12 hours. Thanks to its leak-proof lid, you can carry it in your
bag with confidence and keep your coffee or tea close on busy days. Whatever
you pour in the morning stays close to its original temperature well into the
afternoon. Designed for everyday use, it is a reliable companion at the office,
on the road, and outdoors."

EXAMPLE 2 (few-shot, SPARSE Turkish input — single feature, 33 words, inside
the 30-60 band; note it stays definitional and invents nothing):
Input: "Seramik kupa, el yapımı"
Output: "El yapımı olarak üretilen bu seramik kupa, sıcak veya soğuk
içeceklerinizi keyifle tüketmeniz için tasarlanmıştır. Mutfakta, ofiste veya
çalışma masanızda günlük kullanıma uygundur; kahvenizi ya da çayınızı içerken
elinizin altındaki güvenilir eşlikçiniz olur."
"""


def build_system_prompt(role: str) -> str:
    """Selected role layer + fixed shared layers = full system prompt."""
    return role + "\n" + SHARED_LAYERS


# ---------------------------------------------------------------
# 3) INPUT COLLECTION
# ---------------------------------------------------------------

def collect_product_info() -> str | None:
    """Collects product name and features; returns None on empty input."""
    product_name = input("\nProduct name: ").strip()
    if not product_name:
        print("Warning: You didn't enter a product name.")
        return None

    features = input("Features (comma-separated): ").strip()
    if not features:
        print("Warning: You didn't enter any features — at least one feature is "
              "required to generate a description.")
        return None

    return f"Product name: {product_name}\nFeatures: {features}"


def choose_tone() -> str:
    """Asks for a tone choice and returns the matching role layer."""
    while True:
        choice = input("Choose a tone [1] Professional [2] Casual/Young: ").strip()
        if choice == "1":
            return ROLE_PROFESSIONAL
        if choice == "2":
            return ROLE_CASUAL
        print("Invalid choice — enter 1 or 2.")


# ---------------------------------------------------------------
# 4) GENERATION — API call
# ---------------------------------------------------------------

MAX_RETRIES = 3


def word_limits(product_info: str) -> tuple[int, int]:
    """Kıt girdide (tek özellik) alt sınırı düşür: dürüstlük > dolgu.
    Tuzak ürün senaryosunda (örn. sadece 'el yapımı') kısa ama dürüst
    metin kabul edilir; kelime baskısı halüsinasyonu teşvik etmesin."""
    feature_count = product_info.split("Features:")[1].count(",") + 1
    if feature_count <= 1:
        return 30, 60   # kıt girdi: kısa ama dürüst
    return 60, 90       # normal senaryo


def generate_copy(product_info: str, system_prompt: str) -> str | None:
    """Sends the product info to Claude and returns the description text.
    Feedback-based retry: if the output is out of the word band, the failed
    text is sent back WITH corrective feedback so the model knows exactly
    what to fix, instead of blindly re-rolling the dice.
    Returns None on API errors — the program never crashes."""
    min_words, max_words = word_limits(product_info)

    # Konuşma geçmişi burada birikir: her başarısız deneme,
    # bir sonraki denemeye "ders" olarak eklenir.
    messages = [{"role": "user", "content": product_info}]

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=500,
                temperature=0.8,
                system=system_prompt,
                messages=messages,
            )
            text = response.content[0].text.strip()
        except Exception as e:
            print(f"API error: {e}")
            return None

        word_count = len(text.split())
        if min_words <= word_count <= max_words:
            print(f"(Word count: {word_count} — OK, target {min_words}-{max_words})")
            return text

        print(f"(Attempt {attempt}: {word_count} words — out of "
              f"{min_words}-{max_words} range, retrying with feedback...)")

        # GERİ BİLDİRİM: başarısız çıktıyı ve somut düzeltme talimatını
        # konuşmaya ekle — model bir sonraki turda neyi düzelteceğini bilir.
        direction = "expand" if word_count < min_words else "shorten"
        messages.append({"role": "assistant", "content": text})
        messages.append({
            "role": "user",
            "content": (
                f"Your previous description was {word_count} words, but the "
                f"required length is {min_words}-{max_words} words. "
                f"Rewrite it: {direction} the text to fit the range. "
                f"Keep the same language, the same tone, and use ONLY the "
                f"features already given — do not add any new claims. "
                f"Reply with the description only."
            ),
        })

    # All retries failed — return the last output anyway, with a warning
    print(f"Warning: word count still out of range after {MAX_RETRIES} attempts "
          f"({word_count} words). Returning the last output.")
    return text


# ---------------------------------------------------------------
# 5) BONUS — generation archive (outputs.json)
# ---------------------------------------------------------------

def save_output(product_info: str, tone: str, text: str) -> None:
    """Appends the generated description to outputs.json."""
    record = {
        "product": product_info,
        "tone": tone,
        "text": text,
        "date": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        if os.path.exists(OUTPUT_FILE):
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                archive = json.load(f)
        else:
            archive = []
    except (json.JSONDecodeError, OSError):
        archive = []  # even if the file is corrupted, don't crash — start fresh

    archive.append(record)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------
# 6) MAIN LOOP
# ---------------------------------------------------------------

def main():
    print("=== product-copy-assistant ===")
    print("Enter raw product info, get a publish-ready description. Type 'quit' to exit.")

    while True:
        command = input("\nPress Enter for a new product (type 'quit' to exit): ").strip().lower()
        if command == "quit":
            print("See you!")
            break

        product_info = collect_product_info()
        if product_info is None:
            continue  # empty input — loop restarts

        role = choose_tone()
        tone_name = "Professional" if role == ROLE_PROFESSIONAL else "Casual/Young"

        system_prompt = build_system_prompt(role)
        print("\nGenerating...\n")

        text = generate_copy(product_info, system_prompt)
        if text is None:
            continue  # API error — move on to the next product

        print("-" * 50)
        print(text)
        print("-" * 50)

        save_output(product_info, tone_name, text)
        print(f"(Saved → {OUTPUT_FILE})")


if __name__ == "__main__":
    main()