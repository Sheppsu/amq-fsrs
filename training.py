import json
import random
import time
import logging
import os
from datetime import datetime, timezone
from collections import defaultdict
from fsrs import Scheduler, Card, ReviewLog, Rating, Optimizer


log = logging.getLogger(__name__)


def insert_sorted(songs: list["AnimeSong"], new_song: "AnimeSong"):
    # sorted low to high
    if len(songs) == 0:
        songs.append(new_song)
        return

    low = 0
    high = len(songs)
    while low < high:
        mid = (low + high) // 2
        if new_song < songs[mid]:
            high = mid
        else:
            low = mid + 1

    songs.insert(low, new_song)


def get_rating(answer_time: int | None):
    if answer_time is None:
        return Rating.Again
    elif answer_time <= 10:
        return Rating.Easy
    elif answer_time <= 15:
        return Rating.Good
    return Rating.Hard


class AnimeSong:
    __slots__ = ("card", "anime_id", "list_status", "type", "is_rebroadcast", "is_dub")

    def __init__(self, card: Card, anime_id: int, list_status: int, song_type: int, is_rebroadcast: bool, is_dub: bool):
        self.card: Card = card
        self.anime_id: int = anime_id
        self.list_status: int = list_status  # 1 = watching, 2 = complete, 3 = hold, 4 = dropped, 5 = ptw
        self.type: int = song_type  # 1 = op, 2 = ed, 3 = ins
        self.is_rebroadcast: bool = is_rebroadcast
        self.is_dub: bool = is_dub

    def __le__(self, other):
        return self.card.due <= other.card.due

    def __lt__(self, other):
        return self.card.due < other.card.due

    def __gt__(self, other):
        return self.card.due > other.card.due

    def __ge__(self, other):
        return self.card.due >= other.card.due

    def to_dict(self):
        pass


def check_filter(filter_type: int, boolean: bool):
    if filter_type == 1:
        return True
    if boolean:
        return filter_type == 2
    return filter_type == 3


class Settings:
    __slots__ = ("path", "status_types", "song_types" , "dub_filter", "rebroadcast_filter")

    def __init__(self, path: str, settings: dict):
        self.path: str = path
        self.apply(settings)

    def apply(self, settings):
        self.status_types = settings.get("status_types", [1, 2, 3, 4])
        self.song_types = settings.get("song_types", [1, 2, 3])
        # for filter ones
        # 1 = any
        # 2 = yes
        # 3 = no
        self.dub_filter = settings.get("dub_filter", 1)
        self.rebroadcast_filter = settings.get("rebroadcast_filter", 1)

    def matches_filter(self, song: AnimeSong):
        return (
            song.list_status in self.status_types
            and song.type in self.song_types
            and check_filter(self.dub_filter, song.is_dub)
            and check_filter(self.rebroadcast_filter, song.is_rebroadcast)
        )

    @classmethod
    def from_path_or_default(cls, path: str):
        if not os.path.exists(path):
            return cls(path, {})
        with open(path, "r") as f:
            settings = json.load(f)
            return cls(path, settings)

    def save(self):
        with open(self.path, "w") as f:
            json.dump(self.to_dict(), f)

    def to_dict(self):
        return {
            "status_types": self.status_types,
            "song_types": self.song_types,
            "dub_filter": self.dub_filter,
            "rebroadcast_filter": self.rebroadcast_filter,
        }


class Trainer:
    SAVE_VERSION = 2

    def __init__(self, path, scheduler, existing_cards, new_cards, review_logs, settings):
        self.path: str = path
        self.scheduler: Scheduler = scheduler
        self.existing_cards: list[Card] = sorted(existing_cards, key=lambda c: c.due)
        self.new_cards: list[Card] = new_cards
        self.existing_songs: list[AnimeSong] = []
        self.new_songs: list[AnimeSong] = []
        self.filtered_existing_songs: list[AnimeSong] = []
        self.filtered_new_songs: list[AnimeSong] = []
        self.review_logs: dict[int, list[ReviewLog]] = review_logs
        self.settings: Settings = settings

        self.current_song: AnimeSong | None = None

        self.master_list = None
        self.my_anime_list = None
        self.song_id_to_anime_ids = None
        self.ann_song_info = None
        self.is_ready = False

    def set_master_list(self, master_list):
        self.master_list = master_list
        self.song_id_to_anime_ids = defaultdict(list)
        for anime in master_list["animeMap"].values():
            songs = anime["songLinks"]
            for song in songs["OP"] + songs["ED"] + songs["INS"]:
                self.song_id_to_anime_ids[song["songId"]].append(anime["annId"])

        log.info("Master list loaded")
        if self.my_anime_list is not None:
            self.on_lists_loaded()

    def set_my_list(self, my_list):
        self.my_anime_list = my_list

        log.info("Anime list loaded")
        if self.master_list is not None:
            self.on_lists_loaded()

    def on_lists_loaded(self):
        if self.is_ready:
            return

        log.info("Organizing data...")

        # get information about songs into a more easily usable format
        self.ann_song_info = {}
        my_ann_songs = set()
        for anime_id, list_status in self.my_anime_list.items():
            anime_map = self.master_list["animeMap"]
            anime_info = anime_map.get(anime_id)
            if anime_info is None:
                continue
            songs = anime_info["songLinks"]
            for song in songs["OP"] + songs["ED"] + songs["INS"]:
                if song["uploaded"] == 0:
                    continue
                my_ann_songs.add(song["annSongId"])
                song["annId"] = anime_id
                self.ann_song_info[song["annSongId"]] = song

        new_card_dict = {card.card_id: card for card in self.new_cards}
        existing_card_dict = {card.card_id: card for card in self.existing_cards}

        # add in missing cards
        for ann_song_id in my_ann_songs:
            if new_card_dict.get(ann_song_id) is None and existing_card_dict.get(ann_song_id) is None:
                self.new_cards.append(Card(ann_song_id))

        # populate self.new_songs and self.existing_songs
        for card in self.existing_cards:
            song_info = self.ann_song_info[card.card_id]
            anime_id = song_info["annId"]
            list_status = self.my_anime_list[anime_id]
            self.existing_songs.append(
                AnimeSong(
                    card,
                    anime_id,
                    list_status,
                    song_info["type"],
                    song_info["rebroadcast"] == 1,
                    song_info["dub"] == 1
                )
            )
        for card in self.new_cards:
            song_info = self.ann_song_info[card.card_id]
            anime_id = song_info["annId"]
            list_status = self.my_anime_list[anime_id]
            self.new_songs.append(
                AnimeSong(
                    card,
                    anime_id,
                    list_status,
                    song_info["type"],
                    song_info["rebroadcast"] == 1,
                    song_info["dub"] == 1
                )
            )

        self.existing_cards = []
        self.new_cards = []
        self.update_filtered_songs()

        log.info("Running optimizer...")
        self.optimize_scheduler()

        self.is_ready = True

    @classmethod
    def from_path(cls, path: str, settings_path: str):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                version = data.get("version", 1)
                if version > 1:
                    scheduler = Scheduler.from_dict(data["scheduler"])
                    existing_cards = list(map(Card.from_dict, data["existing_cards"]))
                    new_cards = list(map(Card.from_dict, data["new_cards"]))
                    review_logs = {
                        int(anime_id): list(map(ReviewLog.from_dict, logs))
                        for anime_id, logs in data["review_logs"].items()
                    }
                else:
                    scheduler = Scheduler.from_json(data["scheduler"])
                    existing_cards = list(map(Card.from_json, data["existing_cards"]))
                    new_cards = list(map(Card.from_json, data["new_cards"]))
                    review_logs_list = list(map(ReviewLog.from_json, data["review_logs"]))
                    review_logs = {}
                    for review_log in review_logs_list:
                        l = review_logs.get(review_log.card_id)
                        if l is None:
                            review_logs[review_log.card_id] = [review_log]
                        else:
                            l.append(review_log)

        except FileNotFoundError:
            scheduler = Scheduler()
            existing_cards = []
            new_cards = []
            review_logs = {}

        settings = Settings.from_path_or_default(settings_path)
        return cls(path, scheduler, existing_cards, new_cards, review_logs, settings)

    def save_fsrs_data(self):
        if not self.is_ready:
            return

        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({
                "version": self.SAVE_VERSION,
                "scheduler": self.scheduler.to_dict(),
                "new_cards": list((song.card.to_dict() for song in self.new_songs)),  # type: ignore
                "existing_cards": list((song.card.to_dict() for song in self.existing_songs)),  # type: ignore
                "review_logs": {
                    anime_id: list(map(ReviewLog.to_dict, logs))  # type: ignore
                    for anime_id, logs in self.review_logs.items()
                },
            }, f)

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
        # return current song to respective list
        if self.current_song is not None:
            if self.current_song.card.last_review is None:
                self.new_songs.append(self.current_song)
                if self.settings.matches_filter(self.current_song):
                    self.filtered_new_songs.append(self.current_song)
            else:
                insert_sorted(self.existing_songs, self.current_song)
                if self.settings.matches_filter(self.current_song):
                    insert_sorted(self.filtered_existing_songs, self.current_song)

        now = datetime.now(tz=timezone.utc)
        if len(self.filtered_existing_songs) > 0 and self.filtered_existing_songs[0].card.due <= now:
            self.current_song = self.filtered_existing_songs.pop(0)
            self.existing_songs.remove(self.current_song)
        elif len(self.filtered_new_songs) > 0:
            self.current_song = self.filtered_new_songs.pop(random.randint(0, len(self.filtered_new_songs) - 1))
            self.new_songs.remove(self.current_song)
        else:
            return
        return self.current_song.card.card_id

    def get_schedule_info(self):
        cards_due = 0
        now = datetime.now(tz=timezone.utc)
        # TODO: use binary search
        for song in self.filtered_existing_songs:
            if song.card.due <= now:
                cards_due += 1
            else:
                break

        return {
            "cards_due": cards_due + (1 if self.current_song is not None and self.current_song.card.last_review is not None else 0),
            "new_cards": len(self.filtered_new_songs),
            "total_cards": len(self.filtered_existing_songs) + len(self.filtered_new_songs) + (1 if self.current_song is not None else 0)
        }

    def optimize_scheduler(self):
        start = time.monotonic()

        all_logs = [rl for logs in self.review_logs.values() for rl in logs]
        try:
            optimizer = Optimizer(all_logs)
            params = optimizer.compute_optimal_parameters()
        except:
            log.exception("Optimizer failed, keeping current parameters")
            params = self.scheduler.parameters
        self.scheduler = Scheduler(params)
        for song in self.existing_songs:
            logs = self.review_logs.get(song.card.card_id)
            if logs:
                song.card = self.scheduler.reschedule_card(song.card, logs)
        self.existing_songs = sorted(self.existing_songs)
        self.filtered_existing_songs = sorted(self.filtered_existing_songs)

        log.info(f"Optimizer took {round(time.monotonic() - start, 2)} seconds")

    def save_result(self, answer_time: int | None):
        reviewed_card, review_log = self.scheduler.review_card(
            self.current_song.card,
            get_rating(answer_time),
            review_duration=answer_time
        )

        self.current_song.card = reviewed_card
        insert_sorted(self.existing_songs, self.current_song)
        if self.settings.matches_filter(self.current_song):
            insert_sorted(self.filtered_existing_songs, self.current_song)
        self.current_song = None

        l = self.review_logs.get(reviewed_card.card_id)
        if l is not None:
            l.append(review_log)
        else:
            self.review_logs[reviewed_card.card_id] = [review_log]

        self.save_fsrs_data()

    def apply_settings(self, settings: dict):
        self.settings.apply(settings)
        self.settings.save()
        self.update_filtered_songs()

    def update_filtered_songs(self):
        self.filtered_new_songs = [song for song in self.new_songs if self.settings.matches_filter(song)]
        self.filtered_existing_songs = [song for song in self.existing_songs if self.settings.matches_filter(song)]
