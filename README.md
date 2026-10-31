# amq-fsrs
I made this thing cuz I wanted an efficient way to learn my list, so I basically just combined Anki with amq.

feel free to open any issues or pull requests and I can get to them when I have some free time

## Features
- fsrs
- w minimal interface
- search bar that's kinda meh
- hover answer text at the top to see other answers
- use settings button to filter cards by song type (op, ed, ins, dubbed, rebroadcast) and list status

## Running

**IMPORTANT NOTE:** the program uses your AMQ login info to connect to the AMQ server so that it can get song info, your list, etc.
You might appear online when running the program, although I set it to set your status as offline when connecting, but I
never actually tested if it works. Also since it's logged in, you can't use the site while running the program.

Now how to run it yourself:
- just need [Python](https://www.python.org/), any decently recent version should be fine
- download the code (either with `git clone https://github.com/sheppsu/amq-fsrs` or the green "Code" button on github)
  - I recommend using git because it'll be easier to update things when changes are pushed to the code (using `git pull`)
- make a copy of "template.env" and name it ".env"
  - fill in your username, password, and any other options in there
- open a command prompt and change your working directory to the folder you downloaded with all the files in it (e.g. main.py), then run the following:
  - `py -m pip install -r requirements.txt` to install python requirements
    - this only needs to be run once to set up things
    - also if you're on linux or mac, the python command might be something else like `python` or `python3`
  - `uvicorn main:app` to run the app
    - you can just run only this in the future
    - the program should spit out a url to go to, which will likely be http://127.0.0.1:8000
    - if you see something about http 500 server errors, it means the master list and/or your anime list didn't load for some reason. try stopping (ctrl+c) and starting the program again in that case.
    - there's also some other info logged when it starts up. If you see an error about logging in, try deleting the "session_cookies" file and re-running.
    - just do ctrl+c when you want to stop the program
