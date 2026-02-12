import json
import random
import time
import logging
import os
from datetime import datetime, timezone
from collections import defaultdict
from fsrs import Scheduler, Card, ReviewLog, Rating, Optimizer


log = logging.getLogger(__name__)


# with open("masterlist.json", encoding="utf-8") as f:
#     masterlist = json.load(f)
#     song_id_to_anime_ids = defaultdict(list)
#     for anime in masterlist["animeMap"].values():
#         songs = anime["songLinks"]
#         for song in songs["OP"] + songs["ED"] + songs["INS"]:
#             for name in anime["names"]:
#                 song_id_to_anime_ids[song["songId"]].append(anime["annId"])
#
# with open("mylist.json", encoding="utf-8") as f:
#     mylist = json.load(f)
#     mylist = [anime_id for anime_id, status in mylist.items() if status != 5]
#     ann_song_info = {}
#     my_ann_songs = set()
#     my_songs = set()
#     for anime_id in mylist:
#         songs = masterlist["animeMap"][anime_id]["songLinks"]
#         for song in songs["OP"] + songs["ED"] + songs["INS"]:
#             if song["uploaded"] == 0:
#                 continue
#             my_ann_songs.add(song["annSongId"])
#             ann_song_info[song["annSongId"]] = song
#             my_songs.add(song["songId"])
#     my_ann_songs = list(my_ann_songs)
#     my_songs = list(my_songs)


def insert_sorted(cards: list[Card], new_card: Card):
    inserted = False
    for i, card in enumerate(cards):
        if new_card.due <= card.due:
            cards.insert(i, new_card)
            inserted = True
            break
    if not inserted:
        cards.append(new_card)


def get_rating(answer_time: int | None):
    if answer_time is None:
        return Rating.Again
    elif answer_time <= 10:
        return Rating.Easy
    elif answer_time <= 15:
        return Rating.Good
    return Rating.Hard


class Trainer:
    def __init__(self, path, scheduler, existing_cards, new_cards, review_logs, include_planned):
        self.path: str = path
        self.scheduler: Scheduler = scheduler
        self.existing_cards: list[Card] = sorted(existing_cards, key=lambda c: c.due)
        self.new_cards: list[Card] = sorted(new_cards, key=lambda c: c.due)
        self.review_logs: list[ReviewLog] = review_logs
        self.include_planned = include_planned

        self.current_card: Card | None = None

        self.master_list = None
        self.my_anime_list = None
        self.my_ann_songs = None
        self.song_id_to_anime_ids = None
        self.ann_song_info = None

    @property
    def is_ready(self):
        return self.master_list is not None and self.my_anime_list is not None

    def set_master_list(self, master_list):
        self.master_list = master_list
        self.song_id_to_anime_ids = defaultdict(list)
        for anime in master_list["animeMap"].values():
            songs = anime["songLinks"]
            for song in songs["OP"] + songs["ED"] + songs["INS"]:
                self.song_id_to_anime_ids[song["songId"]].append(anime["annId"])

        log.info("Master list loaded")
        if self.is_ready:
            self.on_lists_loaded()

    def set_my_list(self, my_list):
        self.my_anime_list = [
            anime_id
            for anime_id, status in my_list.items()
            if self.include_planned or status != 5
        ]

        log.info("Anime list loaded")
        if self.is_ready:
            self.on_lists_loaded()

    def on_lists_loaded(self):
        # get information about songs into a more easily usable format
        self.ann_song_info = {}
        my_ann_songs = set()
        for anime_id in self.my_anime_list:
            anime_map = self.master_list["animeMap"]
            anime_info = anime_map.get(anime_id)
            if anime_info is None:
                continue
            songs = anime_info["songLinks"]
            for song in songs["OP"] + songs["ED"] + songs["INS"]:
                if song["uploaded"] == 0:
                    continue
                my_ann_songs.add(song["annSongId"])
                self.ann_song_info[song["annSongId"]] = song
        self.my_ann_songs = list(my_ann_songs)

        # randomly add in missing cards
        for ann_song_id in random.sample(self.my_ann_songs, len(self.my_ann_songs)):
            if not any((card.card_id == ann_song_id for card in self.new_cards + self.existing_cards)):
                self.new_cards.append(Card(ann_song_id))

        log.info("Everything successfully loaded")

    @classmethod
    def from_path(cls, path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                scheduler = Scheduler.from_json(data["scheduler"])
                existing_cards = list(map(Card.from_json, data["existing_cards"]))
                new_cards = list(map(Card.from_json, data["new_cards"]))
                review_logs = list(map(ReviewLog.from_json, data["review_logs"]))
        except FileNotFoundError:
            scheduler = Scheduler()
            existing_cards = []
            new_cards = []
            review_logs = []

        include_planned = bool(int(os.getenv("INCLUDE_PLANNED")))
        if include_planned is None:
            include_planned = False

        return cls(path, scheduler, existing_cards, new_cards, review_logs, include_planned)

    def get_song_info(self, song_id):
        info = self.master_list["songMap"][str(song_id)]
        if info["songArtistId"] is not None:
            info["artist"] = self.master_list["artistMap"][str(info["songArtistId"])]
        if info["songGroupId"] is not None:
            info["group"] = self.master_list["groupMap"][str(info["songGroupId"])]
        return info

    def get_all_anime(self):
        anime_data = {}
        for anime in self.master_list["animeMap"].values():
            anime_data[anime["annId"]] = [name["name"] for name in anime["names"]]
        return anime_data

    def get_valid_answers(self, song_id):
        answers = set()
        for ann_id in self.song_id_to_anime_ids[song_id]:
            for name in self.master_list["animeMap"][str(ann_id)]["names"]:
                answers.add(name["name"])
        return sorted(answers)

    def get_ann_song_info(self, ann_song_id):
        return self.ann_song_info[ann_song_id]

    def get_next_song(self) -> int | None:
        if self.current_card is not None:
            if self.current_card.last_review is None:
                self.new_cards.append(self.current_card)
            else:
                insert_sorted(self.existing_cards, self.current_card)

        now = datetime.now(tz=timezone.utc)
        if len(self.existing_cards) > 0 and self.existing_cards[0].due <= now:
            self.current_card = self.existing_cards.pop(0)
        elif len(self.new_cards) > 0:
            self.current_card = self.new_cards.pop(random.randint(0, len(self.new_cards) - 1))
        else:
            return
        return self.current_card.card_id

    def get_schedule_info(self):
        cards_due = 0
        now = datetime.now(tz=timezone.utc)
        for card in self.existing_cards:
            if card.due <= now:
                cards_due += 1
            else:
                break

        return {
            "cards_due": cards_due + (1 if self.current_card is not None and self.current_card.last_review is not None else 0),
            "new_cards": len(self.new_cards),
            "total_cards": len(self.existing_cards) + len(self.new_cards) + (1 if self.current_card is not None else 0)
        }

    def optimize_scheduler(self):
        start = time.monotonic()

        optimizer = Optimizer(self.review_logs)
        optimal_params = optimizer.compute_optimal_parameters()
        self.scheduler = Scheduler(optimal_params)

        mapped_review_logs = {card.card_id: [] for card in self.existing_cards}
        for review_log in self.review_logs:
            mapped_review_logs[review_log.card_id].append(review_log)
        self.existing_cards = sorted((
            self.scheduler.reschedule_card(card, mapped_review_logs[card.card_id])
            for card in self.existing_cards
        ), key=lambda card: card.due)

        log.info(f"Optimizer took {round(time.monotonic() - start, 2)} seconds")

    def save_result(self, answer_time: int | None):
        reviewed_card, review_log = self.scheduler.review_card(
            self.current_card,
            get_rating(answer_time),
            review_duration=answer_time
        )
        insert_sorted(self.existing_cards, reviewed_card)
        self.review_logs.append(review_log)
        self.current_card = None

        # probably better to only try and optimize after going through some amount
        if len(self.review_logs) >= 50:
            self.optimize_scheduler()

        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({
                "scheduler": self.scheduler.to_json(),
                "new_cards": list(map(Card.to_json, self.new_cards)),  # type: ignore
                "existing_cards": list(map(Card.to_json, self.existing_cards)),  # type: ignore
                "review_logs": list(map(ReviewLog.to_json, self.review_logs)),  # type: ignore
            }, f)
