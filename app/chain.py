"""Deterministic chain-of-title engine.

This layer never calls a model. It rebuilds who held which land when, and raises
red flags with rules that can be tested. Nemotron 3 Ultra explains these findings
and looks for anything the rules miss (see llm.py), but the core checks stay
predictable and auditable.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

from .models import (
    Document,
    Flag,
    Holding,
    Parcel,
    ProposedSale,
    TimelineEvent,
)

EPS = 0.01  # decimals; ignore rounding noise

# Honorifics and common prefixes that vary between documents for the same person.
_HONORIFICS = {
    "md", "mohammad", "mohammed", "muhammad", "mohd", "mst", "mosammat",
    "mrs", "mr", "late", "alhaj", "haji", "sk",
    "মোঃ", "মোহাম্মদ", "মোছাঃ", "মোসাম্মৎ", "মরহুম", "আলহাজ্ব", "হাজী",
}


def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation and honorifics so spelling variants line up."""
    text = unicodedata.normalize("NFC", name or "").lower()
    text = re.sub(r"[.,;:()\-_/]", " ", text)
    tokens = [t for t in text.split() if t and t not in _HONORIFICS]
    return " ".join(tokens)


def name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()


def _date_key(doc: Document) -> str:
    # Undated documents sort last within their type; khatian records come first.
    order = {"khatian": "0", "deed": "1", "mutation": "2"}[doc.doc_type]
    return (doc.date or "9999-12-31") + order


class ChainEngine:
    SIMILAR_LOW = 0.72   # above this, two names are "suspiciously similar"
    SAME_PERSON = 0.999  # after normalisation, treat as the same person

    def __init__(self, documents: list[Document], proposed: ProposedSale | None = None):
        self.documents = documents
        self.proposed = proposed
        self.flags: list[Flag] = []
        self.timeline: list[TimelineEvent] = []
        # holdings[person_key][dag] = area actually backed by a valid chain
        self.holdings: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.display: dict[str, str] = {}
        # first date each person acquired each dag
        self.acquired: dict[str, dict[str, str | None]] = defaultdict(dict)
        # (seller_key, dag) -> list of deed ids already sold
        self.sales_by_seller: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.record_dags: dict[str, float] = {}
        self.record_mouzas: set[str] = set()
        self.record_owner_keys: set[str] = set()
        self.deed_label = {d.id: (d.deed_no or d.id) for d in documents}

    # ---------- helpers ----------
    def _key(self, name: str) -> str:
        k = normalize_name(name)
        self.display.setdefault(k, name)
        return k

    def _flag(self, code, severity, title, detail, doc_ids=(), people=()) -> Flag:
        f = Flag(
            id=f"F{len(self.flags) + 1}",
            code=code,
            severity=severity,
            title=title,
            detail=detail,
            doc_ids=list(doc_ids),
            people=list(people),
        )
        self.flags.append(f)
        return f

    def _closest_known(self, key: str) -> tuple[str | None, float]:
        best, score = None, 0.0
        for k in set(self.holdings) | self.record_owner_keys:
            if k == key:
                continue
            s = SequenceMatcher(None, key, k).ratio()
            if s > score:
                best, score = k, s
        return best, score

    def _future_acquisition(self, key: str, dag: str, after_date: str | None, deeds: list[Document]):
        for d in deeds:
            if d.doc_type != "deed":
                continue
            if after_date and d.date and d.date <= after_date:
                continue
            if any(self._key(b.name) == key for b in d.buyers) and any(p.dag == dag for p in d.parcels):
                return d
        return None

    # ---------- main ----------
    def run(self):
        docs = sorted(self.documents, key=_date_key)
        deeds = [d for d in docs if d.doc_type == "deed"]

        for doc in docs:
            if doc.doc_type == "khatian":
                self._apply_record(doc)
        for doc in docs:
            if doc.doc_type == "deed":
                self._apply_deed(doc, deeds)
            elif doc.doc_type == "mutation":
                self._apply_mutation(doc)

        if self.proposed:
            self._check_proposed(self.proposed)
        self._check_mutations(docs)
        return self

    def _apply_record(self, doc: Document):
        if doc.mouza:
            self.record_mouzas.add(doc.mouza.strip().lower())
        owners = doc.owners or []
        total_share = sum(o.share for o in owners if o.share) or 0
        for parcel in doc.parcels:
            self.record_dags[parcel.dag] = self.record_dags.get(parcel.dag, 0) + parcel.area_decimal
            for o in owners:
                share = o.share if o.share else (1 / len(owners) if owners else 0)
                if total_share and total_share > 1 + EPS:
                    share = share / total_share
                k = self._key(o.name)
                self.record_owner_keys.add(k)
                self.holdings[k][parcel.dag] += parcel.area_decimal * share
                self.acquired[k].setdefault(parcel.dag, None)  # held since the record
        self.timeline.append(
            TimelineEvent(
                id=f"E{len(self.timeline) + 1}",
                date=doc.date,
                kind="record",
                label=f"Recorded owners in khatian {doc.khatian_no or ''}".strip(),
                buyers=[o.name for o in owners],
                parcels=doc.parcels,
                doc_id=doc.id,
            )
        )

    def _apply_deed(self, doc: Document, deeds: list[Document]):
        event_flags: list[str] = []
        seller_keys = [self._key(s.name) for s in doc.sellers]
        buyer_keys = [self._key(b.name) for b in doc.buyers]
        seller_names = [s.name for s in doc.sellers]

        if doc.mouza and self.record_mouzas and doc.mouza.strip().lower() not in self.record_mouzas:
            f = self._flag(
                "MOUZA_MISMATCH", "medium",
                "Mouza doesn't match the record",
                f"Deed {doc.deed_no or doc.id} names mouza '{doc.mouza}', which is not the mouza in the khatian.",
                [doc.id],
            )
            event_flags.append(f.id)

        for parcel in doc.parcels:
            dag, area = parcel.dag, parcel.area_decimal

            if self.record_dags and dag not in self.record_dags:
                f = self._flag(
                    "DAG_NOT_IN_RECORD", "medium",
                    f"Dag {dag} is not in the khatian",
                    f"Deed {doc.deed_no or doc.id} transfers dag {dag}, but the khatian you uploaded does not list it.",
                    [doc.id],
                )
                event_flags.append(f.id)

            held = sum(self.holdings[k].get(dag, 0) for k in seller_keys)

            prior_ids = [d for k in seller_keys for d in self.sales_by_seller[(k, dag)]]
            prior_sales = [self.deed_label[i] for i in prior_ids]
            if held <= EPS and prior_sales:
                f = self._flag(
                    "DOUBLE_SALE", "high",
                    "Same land sold more than once",
                    f"{', '.join(seller_names)} had already sold all their land in dag {dag} "
                    f"(deed {', '.join(prior_sales)}), then sold {area:g} decimals again in deed "
                    f"{doc.deed_no or doc.id}.",
                    [doc.id] + prior_ids, seller_names,
                )
                event_flags.append(f.id)
            elif held <= EPS:
                # Seller holds nothing in this dag. Work out why.
                future = None
                for k in seller_keys:
                    future = future or self._future_acquisition(k, dag, doc.date, deeds)
                if future:
                    f = self._flag(
                        "SALE_BEFORE_ACQUISITION", "high",
                        "Land sold before the seller owned it",
                        f"{', '.join(seller_names)} sold dag {dag} on {doc.date}, but only acquired it on "
                        f"{future.date} (deed {future.deed_no or future.id}).",
                        [doc.id, future.id], seller_names,
                    )
                    event_flags.append(f.id)
                else:
                    similar, score = None, 0.0
                    for k in seller_keys:
                        cand, s = self._closest_known(k)
                        if s > score:
                            similar, score = cand, s
                    if similar and score >= self.SIMILAR_LOW:
                        f = self._flag(
                            "NAME_MISMATCH", "high",
                            "Seller's name doesn't match the owner on record",
                            f"Deed {doc.deed_no or doc.id} is signed by '{', '.join(seller_names)}', but the "
                            f"owner on record is '{self.display[similar]}'. These may be different people.",
                            [doc.id], seller_names + [self.display[similar]],
                        )
                    else:
                        f = self._flag(
                            "MISSING_LINK", "high",
                            "Missing link in the ownership chain",
                            f"Nothing you uploaded shows how {', '.join(seller_names)} came to own dag {dag} "
                            f"before selling it in deed {doc.deed_no or doc.id}.",
                            [doc.id], seller_names,
                        )
                    event_flags.append(f.id)
            elif area > held + EPS:
                prior = prior_sales
                if prior:
                    f = self._flag(
                        "DOUBLE_SALE", "high",
                        "Same land sold more than once",
                        f"{', '.join(seller_names)} had already sold land in dag {dag} "
                        f"(deed {', '.join(prior)}). Deed {doc.deed_no or doc.id} sells {area:g} decimals "
                        f"but only {held:g} decimals were left.",
                        [doc.id] + prior_ids, seller_names,
                    )
                else:
                    f = self._flag(
                        "OVERSELL", "high",
                        "More land sold than the seller owned",
                        f"Deed {doc.deed_no or doc.id} sells {area:g} decimals of dag {dag}, but "
                        f"{', '.join(seller_names)} held only {held:g} decimals.",
                        [doc.id], seller_names,
                    )
                event_flags.append(f.id)

            # Transfer only what was actually held; the rest is unbacked.
            transferable = min(area, held)
            if transferable > EPS:
                for k in seller_keys:
                    have = self.holdings[k].get(dag, 0)
                    take = transferable * (have / held) if held else 0
                    self.holdings[k][dag] = max(0.0, have - take)
            for k in buyer_keys:
                self.holdings[k][dag] += transferable / max(len(buyer_keys), 1)
                self.acquired[k].setdefault(dag, doc.date)
            for k in seller_keys:
                self.sales_by_seller[(k, dag)].append(doc.id)

        self.timeline.append(
            TimelineEvent(
                id=f"E{len(self.timeline) + 1}",
                date=doc.date,
                kind="sale",
                label=f"Sale deed {doc.deed_no or ''}".strip(),
                sellers=seller_names,
                buyers=[b.name for b in doc.buyers],
                parcels=doc.parcels,
                doc_id=doc.id,
                flag_ids=event_flags,
            )
        )

    def _apply_mutation(self, doc: Document):
        self.timeline.append(
            TimelineEvent(
                id=f"E{len(self.timeline) + 1}",
                date=doc.date,
                kind="mutation",
                label="Mutation (namjari)",
                buyers=[o.name for o in doc.owners],
                parcels=doc.parcels,
                doc_id=doc.id,
            )
        )

    def _check_mutations(self, docs: list[Document]):
        mutated = {self._key(o.name) for d in docs if d.doc_type == "mutation" for o in d.owners}
        seller = self._key(self.proposed.seller) if self.proposed else None
        candidates = [seller] if seller else [
            k for k, dags in self.holdings.items()
            if k not in self.record_owner_keys and sum(dags.values()) > EPS
        ]
        for k in candidates:
            if k and k not in mutated and k not in self.record_owner_keys:
                self._flag(
                    "NO_MUTATION", "medium",
                    "No mutation in the current owner's name",
                    f"No mutation (namjari) record was uploaded in the name of {self.display.get(k, k)}. "
                    "Without it, the land office still shows someone else as owner.",
                    [], [self.display.get(k, k)],
                )

    def _check_proposed(self, p: ProposedSale):
        k = self._key(p.seller)
        held = self.holdings.get(k, {}).get(p.dag, 0.0)
        flag_ids = []
        if held <= EPS:
            f = self._flag(
                "PROPOSED_UNBACKED", "high",
                "The seller has no valid title to this land",
                f"Based on the documents, {p.seller} holds no valid share of dag {p.dag}, "
                f"but is offering to sell {p.area_decimal:g} decimals.",
                [], [p.seller],
            )
            flag_ids.append(f.id)
        elif p.area_decimal > held + EPS:
            f = self._flag(
                "PROPOSED_OVERSELL", "high",
                "You're being offered more land than the seller owns",
                f"{p.seller} is offering {p.area_decimal:g} decimals of dag {p.dag}, but the documents "
                f"back only {held:g} decimals.",
                [], [p.seller],
            )
            flag_ids.append(f.id)
        self.timeline.append(
            TimelineEvent(
                id=f"E{len(self.timeline) + 1}",
                date=None,
                kind="proposed",
                label="Your proposed purchase",
                sellers=[p.seller],
                buyers=["You"],
                parcels=[Parcel(dag=p.dag, area_decimal=p.area_decimal)],
                flag_ids=flag_ids,
            )
        )

    # ---------- outputs ----------
    def holdings_list(self) -> list[Holding]:
        out = []
        for k, dags in self.holdings.items():
            for dag, area in dags.items():
                if area > EPS:
                    out.append(Holding(name=self.display.get(k, k), dag=dag, area_decimal=round(area, 2)))
        return sorted(out, key=lambda h: (h.dag, -h.area_decimal))

    def risk(self) -> str:
        sev = {f.severity for f in self.flags}
        if "high" in sev:
            return "high"
        if "medium" in sev:
            return "medium"
        return "low"


def analyze_chain(documents: list[Document], proposed: ProposedSale | None = None) -> ChainEngine:
    return ChainEngine(documents, proposed).run()
