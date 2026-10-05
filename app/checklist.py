"""Bilingual (English / Bangla) verification checklist.

The template checklist always works, even with no model available. When a
Token Factory key is set, Nemotron Super rewrites and orders it for the
specific case (see llm.py), and falls back to this list on any error.
"""
from __future__ import annotations

from .models import ChecklistItem, Flag

BASELINE: list[ChecklistItem] = [
    ChecklistItem(
        en="Get a certified copy of the latest khatian (record of rights) from the AC Land office and compare it with the copy you were given.",
        bn="এসি ল্যান্ড অফিস থেকে সর্বশেষ খতিয়ানের সার্টিফাইড কপি তুলুন এবং আপনাকে দেওয়া কপির সাথে মিলিয়ে দেখুন।",
        priority="must",
    ),
    ChecklistItem(
        en="Ask the sub-registry office to search (tallashi) for every deed registered on this dag, including any after the seller's purchase.",
        bn="সাব-রেজিস্ট্রি অফিসে এই দাগে নিবন্ধিত সব দলিলের তল্লাশি করান, বিক্রেতার কেনার পরের দলিলসহ।",
        priority="must",
    ),
    ChecklistItem(
        en="Check the seller's National ID card against the name in the deed and the khatian.",
        bn="বিক্রেতার জাতীয় পরিচয়পত্র দলিল ও খতিয়ানের নামের সাথে মিলিয়ে দেখুন।",
        priority="must",
    ),
    ChecklistItem(
        en="See up-to-date land development tax receipts (dakhila) in the seller's name.",
        bn="বিক্রেতার নামে হালনাগাদ ভূমি উন্নয়ন কর (খাজনা) পরিশোধের দাখিলা দেখুন।",
        priority="should",
    ),
    ChecklistItem(
        en="Have a surveyor measure the land and confirm the boundaries match the dag on the mouza map.",
        bn="সার্ভেয়ার দিয়ে জমি মেপে নিশ্চিত হোন যে সীমানা মৌজা নকশার দাগের সাথে মেলে।",
        priority="should",
    ),
    ChecklistItem(
        en="Ask neighbours and the local union office whether there is any dispute or court case over this land.",
        bn="প্রতিবেশী ও স্থানীয় ইউনিয়ন অফিসে জিজ্ঞেস করুন জমি নিয়ে কোনো বিরোধ বা মামলা আছে কিনা।",
        priority="should",
    ),
    ChecklistItem(
        en="Take advice from a land lawyer before you pay any advance (bayna).",
        bn="কোনো বায়না দেওয়ার আগে একজন ভূমি আইনজীবীর পরামর্শ নিন।",
        priority="must",
    ),
]


def _for_flag(flag: Flag) -> ChecklistItem | None:
    who = ", ".join(flag.people) if flag.people else "the seller"
    templates = {
        "OVERSELL": (
            f"Confirm exactly how much land {who} owned in this dag before the sale; the deed sells more than the records show.",
            f"এই দাগে বিক্রির আগে {who}-এর ঠিক কতটুকু জমি ছিল তা নিশ্চিত করুন; দলিলে রেকর্ডের চেয়ে বেশি জমি বিক্রি দেখানো হয়েছে।",
        ),
        "DOUBLE_SALE": (
            f"Ask the sub-registry office to list every deed in which {who} sold land in this dag; the same land appears to be sold twice.",
            f"{who} এই দাগে যত দলিলে জমি বিক্রি করেছেন সবগুলোর তালিকা সাব-রেজিস্ট্রি অফিস থেকে নিন; একই জমি দুবার বিক্রির আশঙ্কা আছে।",
        ),
        "MISSING_LINK": (
            f"Ask for the source deed (via dalil) that shows how {who} became the owner.",
            f"{who} কীভাবে মালিক হলেন তা দেখাতে উৎস দলিল (বায়া দলিল) চেয়ে নিন।",
        ),
        "SALE_BEFORE_ACQUISITION": (
            "Verify the dates of both deeds at the sub-registry office; land was sold before the seller owned it.",
            "সাব-রেজিস্ট্রি অফিসে দুটি দলিলের তারিখ যাচাই করুন; মালিক হওয়ার আগেই জমি বিক্রির রেকর্ড আছে।",
        ),
        "NAME_MISMATCH": (
            f"Confirm whether {who} are the same person, using the National ID or a succession certificate (warish sanad).",
            f"{who} একই ব্যক্তি কিনা জাতীয় পরিচয়পত্র বা ওয়ারিশ সনদ দিয়ে নিশ্চিত করুন।",
        ),
        "NO_MUTATION": (
            f"Check at the AC Land office whether mutation (namjari) has been completed in the name of {who}, and ask for the DCR.",
            f"এসি ল্যান্ড অফিসে {who}-এর নামে নামজারি সম্পন্ন হয়েছে কিনা দেখুন এবং ডিসিআর চেয়ে নিন।",
        ),
        "DAG_NOT_IN_RECORD": (
            "Match the dag numbers in the deed against the khatian and the mouza map.",
            "দলিলের দাগ নম্বর খতিয়ান ও মৌজা নকশার সাথে মিলিয়ে দেখুন।",
        ),
        "MOUZA_MISMATCH": (
            "Confirm the mouza name and JL number in the deed match the khatian.",
            "দলিলের মৌজার নাম ও জেএল নম্বর খতিয়ানের সাথে মেলে কিনা নিশ্চিত করুন।",
        ),
        "PROPOSED_OVERSELL": (
            f"Do not agree to buy more land than {who} can prove they own; reduce the area or get the missing title documents.",
            f"{who} যতটুকু জমির মালিকানা প্রমাণ করতে পারেন তার বেশি কিনতে রাজি হবেন না; জমির পরিমাণ কমান বা প্রয়োজনীয় দলিল সংগ্রহ করুন।",
        ),
        "PROPOSED_UNBACKED": (
            f"Do not pay any advance until {who} shows a complete chain of documents to this land.",
            f"{who} এই জমির সম্পূর্ণ মালিকানার কাগজ না দেখানো পর্যন্ত কোনো বায়না দেবেন না।",
        ),
    }
    if flag.code not in templates:
        return None
    en, bn = templates[flag.code]
    return ChecklistItem(en=en, bn=bn, priority="must" if flag.severity == "high" else "should", related_flag=flag.id)


def build_checklist(flags: list[Flag]) -> list[ChecklistItem]:
    specific = [item for f in flags if (item := _for_flag(f))]
    items = specific + BASELINE
    return sorted(items, key=lambda i: 0 if i.priority == "must" else 1)
