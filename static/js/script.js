const player = document.getElementById("video-player");
const answerBox = document.getElementById("answer-box");
const dropdownSelection = document.getElementById("anime-dropdown");
const volumeSlider = document.getElementById("volume-slider");
const videoPlayerTimer = document.getElementById("video-player-timer");
const answerText = document.getElementById("answer-text");
const videoCover = document.getElementById("video-player-cover");
const scheduleInfo = document.getElementById("schedule-info");
const playbackBtn = document.getElementById("playback-btn");
const settingsBtn = document.getElementById("settings-btn");
const settingsPanel = document.getElementById("settings-panel");
const settingsApplyBtn = document.getElementById("settings-apply-btn");
const settingsOptions = {
    status: [
        document.getElementById("setting-status-watching"),
        document.getElementById("setting-status-completed"),
        document.getElementById("setting-status-hold"),
        document.getElementById("setting-status-dropped"),
        document.getElementById("setting-status-ptw")
    ],
    songInfo: {
        types: [
            document.getElementById("setting-song-op"),
            document.getElementById("setting-song-ed"),
            document.getElementById("setting-song-ins")
        ],
        dubbed: document.getElementById("setting-song-dubbed"),
        rebroadcast: document.getElementById("setting-song-rebroadcast")
    }
}

const PLAY_DURATION = 20;

let animeData = null;
let currentAnime = null;
let currentAnswers = null;
let currentSongId = null;
let currentAnnSongId = null;
let startedAt = 0;
let reviewing = false;
let songStartPoint = null;
let paused = true;
let loadingNext = false;
let fetchingNext = false;


async function getNextAnime() {
	if (fetchingNext) {
		return;
	}
	fetchingNext = true;
	
    const resp = await fetch("/next");
    const data = await resp.json();
    let filename = data.song.fileName;
    if ("fileNameMap" in data.song) {
        const filenames = data.song.fileNameMap;
        if ("720" in filenames) {
            filename = filenames["720"];
        } else if ("480" in filenames) {
            filename = filenames["480"];
        }
    }
	
	fetchingNext = false;
	
    return {
        animeInfo: animeData[data.song.annId],
        answers: data.answers,
        songId: data.song.songId,
        annSongId: data.song.annSongId,
        songUrl: "https://nawdist.animemusicquiz.com/" + filename
    };
}

async function getCurrentSongInfo() {
    const songInfoReq = fetch(`/song-info/${currentSongId}`);
    const annSongInfoReq = fetch(`/ann-song-info/${currentAnnSongId}`);

    const songInfoResp = await songInfoReq;
    const songInfo = await songInfoResp.json();
    const annSongInfoResp = await annSongInfoReq;
    songInfo.annInfo = await annSongInfoResp.json();
    return songInfo;
}

async function getScheduleInfo() {
    const resp = await fetch("/schedule-info");
    return await resp.json();
}

function showScheduleInfo() {
    getScheduleInfo().then((info) => {
        const undueCards = info.total_cards - info.new_cards;
        scheduleInfo.innerText = `Cards due: ${info.cards_due} / ${undueCards} | New Cards: ${info.new_cards} / ${info.total_cards}`;
    });
}

function setPlayer(songUrl) {
    player.src = songUrl;
    player.load();
}

function next() {
    stopTimer();
    loadingNext = true;
    getNextAnime().then((data) => {
        currentAnime = data.animeInfo;
        currentAnswers = data.answers;
        currentSongId = data.songId;
        currentAnnSongId = data.annSongId;
        reviewing = false;
        loadingNext = false;
        setPlayer(data.songUrl);
        videoPlayerTimer.innerText = "20";
        videoCover.classList.remove("hide");
        answerText.innerText = "";
        answerBox.disabled = false;
        answerBox.value = "";
        answerBox.className = "";
        answerBox.focus();
    });
}

function review() {
    reviewing = true;

    player.currentTime = songStartPoint;
    player.play();

    answerText.innerText = currentAnime[0];
    answerBox.disabled = true;
    videoCover.classList.add("hide");
    getCurrentSongInfo().then((info) => {
        const artist = "artist" in info ? info.artist.name : info.group.name;
        const songType = ["", "OP", "ED", "INS"][info.annInfo.type];
        const songN = info.annInfo.number === 0 ? "" : info.annInfo.number;
        answerText.innerText = `${currentAnime[0]} | ${artist} - ${info.name} | ${songType}${songN}`;
    });
}

function removeChildren(elm) {
    while (elm.children.length > 0) {
        elm.children.item(0).remove();
    }
}

function createDropdownChoice(text) {
    const elm = document.createElement("li");
    elm.textContent = text
    elm.classList.add("dropdown-choice");
    return elm
}

const EQUIVALENT_CHARS = [
    ["×", "x"],
    ["é", "e"]
]
function sanitizeTitle(title) {
    let text = title.toLowerCase().trim();
    for (const [replacedChar, newChar] of EQUIVALENT_CHARS) {
        text = text.replace(replacedChar, newChar);
    }
    return text;
}

function submitAnswer(text) {
    const lowerAnswers = currentAnswers.map(sanitizeTitle);
    const answerTime = lowerAnswers.includes(sanitizeTitle(text)) ?
        Math.round((Date.now() - startedAt) / 1000) : null;
    fetch("/answer", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({
            answer_time: answerTime
        })
    }).then(() => showScheduleInfo());

    if (answerTime === null) {
        answerBox.classList.add("result-wrong");
    } else {
        answerBox.classList.add("result-correct");
    }

    console.log("########## ANSWERS #############");
    for (const answer of currentAnswers) {
        console.log(answer);
    }
}

let currentOptions = [];
let selectedOption = null;
let animeList = null;
let cleanAnimeList = null;

function updateDropdownSelection(clear) {
    removeChildren(dropdownSelection);
    currentOptions = [];
    selectedOption = null;

    if (clear) {
        return;
    }

    const text = sanitizeTitle(answerBox.value);
    if (text.length === 0) {
        return;
    }

	const startMatches = [];
	const otherMatches = [];
    for (const [i, anime] of Object.entries(cleanAnimeList)) {
		if (anime.startsWith(text)) {
			startMatches.push(animeList[parseInt(i)])
			
			if (startMatches.length === 20) {
				break;
			}
		}
        else if (anime.includes(text)) {
            otherMatches.push(animeList[parseInt(i)])
        }
    }
	
	currentOptions = startMatches.slice(0, startMatches.length).concat(otherMatches.slice(0, 20 - startMatches.length));
	
	for (const match of currentOptions) {
		dropdownSelection.appendChild(createDropdownChoice(match));
	}
}

function goToNextState() {
    updateDropdownSelection(true);
    if (!reviewing) {
        submitAnswer(answerBox.value);
        review();
    } else if (!paused) {
        next();
    }
}

function setupAnswerBox(data) {
    animeData = data;
    animeList = Object.values(animeData).flat().sort();
    let i = 0;
    while (i < animeList.length - 1) {
        if (animeList[i] === animeList[i + 1]) {
            animeList = animeList.slice(0, i).concat(animeList.slice(i+1))
        } else {
            i += 1
        }
    }
    cleanAnimeList = animeList.map(sanitizeTitle);

    answerBox.addEventListener("input", () => updateDropdownSelection(false));
    answerBox.addEventListener("keydown", (evt) => {
        let newSelectedOption = null;
        if (evt.key === "ArrowDown") {
            if (selectedOption === null) {
                newSelectedOption = 0;
            } else if (selectedOption !== currentOptions.length - 1) {
                newSelectedOption = selectedOption + 1;
            }
            evt.preventDefault();
        } else if (evt.key === "ArrowUp") {
            if (selectedOption !== 0 && selectedOption !== null) {
                newSelectedOption = selectedOption - 1;
            }
            evt.preventDefault();
        }

        if (newSelectedOption !== null) {
            if (selectedOption !== null) {
                dropdownSelection.children.item(selectedOption).classList.remove("selected");
            }
            dropdownSelection.children.item(newSelectedOption).classList.add("selected");
            selectedOption = newSelectedOption;
        }
    });
    document.addEventListener("keydown", (evt) => {
        if (evt.key === "Enter") {
            if (selectedOption !== null) {
                answerBox.value = dropdownSelection.children.item(selectedOption).innerText;
            }
            goToNextState();
            evt.preventDefault();
        }
    });
}

let intervalId = null;
let timeoutId = null;
function startTimer() {
    if (intervalId !== null) {
        clearInterval(intervalId);
    }
    if (timeoutId !== null) {
        clearTimeout(timeoutId);
    }

    startedAt = Date.now();
    intervalId = setInterval(() => {
        videoPlayerTimer.innerText = "" + Math.max(Math.floor(PLAY_DURATION - ((Date.now() - startedAt) / 1000)), 0);
    });
    timeoutId = setTimeout(() => {
        clearInterval(intervalId);
        intervalId = null;
        timeoutId = null;
        goToNextState();
    }, PLAY_DURATION * 1000);
}

function stopTimer() {
    if (intervalId !== null) {
        clearInterval(intervalId);
        intervalId = null;
    }
    if (timeoutId !== null) {
        clearTimeout(timeoutId);
        timeoutId = null;
    }
}

function loadSettings() {
    fetch("/settings").then((resp) => resp.json()).then((data) => {
        for (const option of settingsOptions.status) {
            option.checked = false;
        }
        for (const i of data.status_types) {
            settingsOptions.status[i - 1].checked = true;
        }
        for (const option of settingsOptions.songInfo.types) {
            option.checked = false;
        }
        for (const i of data.song_types) {
            settingsOptions.songInfo.types[i - 1].checked = true;
        }
        settingsOptions.songInfo.dubbed.value = data.dub_filter;
        settingsOptions.songInfo.rebroadcast.value = data.rebroadcast_filter;
    });
}

export function setup() {
    loadSettings();

    fetch("/anime").then((resp) => resp.json().then(setupAnswerBox));

    player.volume = 0.2;
    player.addEventListener("loadedmetadata", () => {
        songStartPoint = Math.max(player.duration - PLAY_DURATION, 0) * Math.random();
        player.currentTime = songStartPoint;
        player.play();
    });
    let firstPlay = false;
    player.addEventListener("seeked", () => {
        firstPlay = true;
    })
    player.addEventListener("playing", () => {
        if (firstPlay) {
            startTimer();
            firstPlay = false;
        }
    });

    volumeSlider.value = player.volume;
    volumeSlider.addEventListener("change", () => {
        player.volume = volumeSlider.value;
    });

    playbackBtn.addEventListener("click", () => {
        paused = !paused;
        if (timeoutId === null && !loadingNext) {
            next();
        }
        playbackBtn.innerText = paused ? "unpause" : "pause";
    });

    settingsBtn.addEventListener("click", () => {
        if (settingsPanel.classList.contains("hide")) {
            settingsPanel.classList.remove("hide");
        } else {
            settingsPanel.classList.add("hide");
        }
    });
    let debounce = false;
    settingsApplyBtn.addEventListener("click", () => {
        if (debounce) {
            return;
        }
        debounce = true;

        const settings = {
            status_types: [],
            song_types: []
        }
        for (let i=0; i<settingsOptions.status.length; i++) {
            if (settingsOptions.status[i].checked) {
                settings.status_types.push(i + 1);
            }
        }
        for (let i=0; i<settingsOptions.songInfo.types.length; i++) {
            if (settingsOptions.songInfo.types[i].checked) {
                settings.song_types.push(i + 1);
            }
        }
        settings.dub_filter = settingsOptions.songInfo.dubbed.value;
        settings.rebroadcast_filter = settingsOptions.songInfo.rebroadcast.value;

        fetch("/settings", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(settings)
        }).then((resp) => {
            if (resp.status === 200) {
                showScheduleInfo()
            }
            debounce = false;
        }).catch(() => debounce = false);
    });

    showScheduleInfo();
    setInterval(showScheduleInfo, 5000);
}
