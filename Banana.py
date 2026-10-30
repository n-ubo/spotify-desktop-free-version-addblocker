from win32gui import CloseWindow, EnumWindows, GetWindowText, GetClassName, PostMessage
from win32api import OpenProcess
from win32process import GetWindowThreadProcessId, GetModuleFileNameEx
import tkinter as tk
from tkinter import *
from tkinter import filedialog, messagebox
from tkinter.ttk import *
from time import sleep
import signal
import subprocess, re, os
from notifypy import Notify
import json
import ctypes
import copy
import sys
import threading
import pystray
from PIL import Image

def resource(relative):
    # icons are bundled into the exe, PyInstaller unpacks them to sys._MEIPASS
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)

name='Banana'
banana=resource(r'assets\banana.ico')

# user settings live in %APPDATA%\Banana, so the exe can be put (or sent) anywhere
APP_DIR = os.path.join(os.environ['APPDATA'], 'Banana')
SETTINGS_FILE = os.path.join(APP_DIR, 'settings.json')
DEFAULT_SPOTIFY = os.path.join(os.environ['APPDATA'], 'Spotify', 'Spotify.exe')

DEFAULT_SETTINGS = {
    "settings": {
        "path": "",
        "start_notification": {"enabled": 1, "title": "Start notification on banana launch"},
        "found_notification": {"enabled": 1, "title": "Advertisement found notification"},
        "debug_notification": {"enabled": 1, "title": "Killed procceses notification"},
        "setting_startup": {"enabled": 1, "title": "Open this menu on banana launch"},
        "start_on_launch": {"enabled": 0, "title": "Start banana on start up"},
        "blacklist_notifications": {"enabled": 0, "title": "Banana prompt to help block more adds"},
    },
    "blacklist": [
        "Advertisement",
        "Bel of chat met ons, want dat lucht op!",
        "Stichting Massaschade & Consument",
    ],
}

# window titles spotify shows while paused or idle
IDLE_TITLES = ('Spotify', 'Spotify Free', 'Spotify Premium')
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# media commands posted straight to spotify's window, so no other app or focus is involved
WM_APPCOMMAND = 0x0319
APPCOMMAND_MEDIA_NEXTTRACK = 11
APPCOMMAND_MEDIA_PLAY_PAUSE = 14

def load_settings():
    # start from the defaults and lay the saved values over them,
    # so settings added in newer versions show up without breaking old files
    data = copy.deepcopy(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE) as f:
            saved = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        saved = {}
    for key, value in saved.get('settings', {}).items():
        if key not in data['settings']:
            continue
        if isinstance(value, dict):
            data['settings'][key]['enabled'] = value.get('enabled', data['settings'][key]['enabled'])
        else:
            data['settings'][key] = value
    if 'blacklist' in saved:
        data['blacklist'] = saved['blacklist']
    if data['settings']['path'] == "" and os.path.exists(DEFAULT_SPOTIFY):
        data['settings']['path'] = DEFAULT_SPOTIFY
    return data

def save_settings(data):
    os.makedirs(APP_DIR, exist_ok=True)
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(data, f, indent=4)

myappid = 'mycompany.myproduct.subproduct.version'
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

# hide cmd
import win32console
import win32gui
win = win32console.GetConsoleWindow()
win32gui.ShowWindow(win, 0)

class Actions():

    def media_command(hwnd, command):
        PostMessage(hwnd, WM_APPCOMMAND, hwnd, command << 16)

    def kill(app):
        notified=False
        found=0
        killed=0
        cmd = 'tasklist /FO CSV /NH'
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        for line in proc.stdout:
            procces_info=str(line)
            if app in procces_info.lower():
                found+=1
                if notified==False:
                    notified=True
                    js=load_settings()
                    if js['settings']['found_notification']['enabled']==1:
                        notification = Notify()
                        notification.title = 'Advertisement'
                        notification.icon = banana
                        notification.application_name = name
                        notification.message = 'Add found in: '+app
                        # don't wait for the toast, it holds up the restart by a second or more
                        notification.send(block=False)
                if re.findall(r'[0-9]{3,6}', procces_info):
                    pid=re.findall(r'[0-9]{3,6}', procces_info)[0]
                    print('attempting to kill: '+pid)
                    try:
                        os.kill(int(pid),signal.SIGTERM)
                    except:
                        print('failed to kill: '+pid)
                    else:
                        print('killed: '+pid)
                        killed+=1
        return found, killed

    def resume(reply, app):
        # a freshly started spotify can ignore commands until it has loaded,
        # so keep pressing play until the title shows a song again
        # check often, but only press again every 1.5s so a slow title update doesn't pause it again
        for tries in range(0, 45):
            hwnd, title = Actions.spotify_window()
            if hwnd and title not in IDLE_TITLES:
                break
            if hwnd and tries % 5 == 0:
                Actions.media_command(hwnd, APPCOMMAND_MEDIA_PLAY_PAUSE)
            sleep(.3)
        if hwnd:
            Actions.media_command(hwnd, APPCOMMAND_MEDIA_NEXTTRACK)
        js=load_settings()
        if js['settings']['debug_notification']['enabled']==1:
            notification = Notify()
            notification.title = 'Add skipped'
            notification.icon = banana
            notification.application_name = name
            notification.message = 'Succesfully resumed '+app+', killed: '+str(reply[1])+' of '+str(reply[0])+' '+app+' processes.'
            notification.send(block=False)

    def escape(reason):
        notification = Notify()
        notification.title = 'Closing Banana.'
        notification.icon = banana
        notification.application_name = name
        notification.message = reason
        notification.send()
        Actions.shutdown()

    def apology(app):
        notification = Notify()
        notification.title = 'Application not found'
        notification.icon = banana
        notification.application_name = name
        notification.message = app+' could not be opened, closing banana.'
        notification.send()
        Actions.shutdown()

    def error():
        notification = Notify()
        notification.title = 'Whoops'
        notification.icon = banana
        notification.application_name = name
        notification.message = 'Something unknown went wrong, closing banana.'
        notification.send()
        Actions.shutdown()

    def open_spotify(path):
        if os.path.exists(path):
            # --minimized is what spotify's own autostart uses, it opens without grabbing focus
            subprocess.Popen([path, '--minimized'], cwd=os.path.dirname(path))
        else:
            # microsoft store installs can't be started by path, the protocol works for both
            os.startfile('spotify:')

    def spotify_window():
        # spotify's main window is a chromium window owned by Spotify.exe
        found = []
        def check(hwnd, _):
            title = GetWindowText(hwnd)
            if not title or GetClassName(hwnd) != 'Chrome_WidgetWin_1':
                return
            _, pid = GetWindowThreadProcessId(hwnd)
            try:
                exe = GetModuleFileNameEx(OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid), 0)
            except Exception:
                return
            if exe.lower().endswith('spotify.exe'):
                found.append((hwnd, title))
        EnumWindows(check, None)
        return found[0] if found else (None, None)

    def is_add(title, blacklist):
        # songs and podcasts are always "artist - title", adds are just the advertiser name
        if title is None or title in IDLE_TITLES:
            return False
        return ' - ' not in title or title in blacklist

    def restart_spotify(path):
        reply=Actions.kill('spotify')
        Actions.open_spotify(path)
        for tries in range(0, 50):
            sleep(.2)
            hwnd, title = Actions.spotify_window()
            if hwnd:
                CloseWindow(hwnd)
                break
        else:
            Actions.apology('spotify')
        Actions.resume(reply, 'spotify')

    def shutdown():
        # remove the tray icon first, otherwise it lingers until hovered
        if GUI.tray:
            GUI.tray.stop()
        os._exit(0)

class app(Actions):
    def main(self):
        print('running...')
        js=load_settings()
        window=GUI()
        window.CreateWindow()
        if js['settings']['setting_startup']['enabled']==1 or not os.path.exists(js['settings']['path']):
            window.show()
        else:
            window.start_listening()
        window.master.mainloop()

    def listen():
        try:
            app.watch()
        except Exception:
            Actions.escape('Banana Interrupted. Exception E.')

    def watch():
        js=load_settings()
        if js['settings']['start_notification']['enabled']==1:
            notification = Notify()
            notification.title = 'Banana started'
            notification.icon = banana
            notification.application_name = name
            notification.message = 'Listening for window changes.'
            notification.send()

        while True:
            sleep(.5)
            hwnd, title = Actions.spotify_window()
            if Actions.is_add(title, js['blacklist']):
                print('add detected: '+title)
                Actions.restart_spotify(js['settings']['path'])
class events():
    def start(self, window):
        window.start_listening()

    def refresh(self, window):
        window.CreateWindow()

    def getPath(self):
        return load_settings()["settings"]['path']

    def setNewPath(self, window):
        filename = filedialog.askopenfilename(initialdir = "/",title = "Select Spotify.exe",filetypes = (("exe files","*.exe"),("all files","*.*")))
        if not filename:
            return
        data = load_settings()
        data["settings"]['path'] = os.path.normpath(filename)
        save_settings(data)
        self.refresh(window)
        return filename

    def changeNotifications(self, js, type):
        data = load_settings()
        if data["settings"][type]['enabled']==1:
            data["settings"][type]['enabled']= 0
        else:
            data["settings"][type]['enabled']= 1
        save_settings(data)

# Create Frame
class GUI():
    tray = None

    def __init__(self):
        self.listening = False
        self.master = Tk()
        self.master.withdraw()
        self.master.geometry("600x300")
        self.master.title('Spotify with Banana.py')
        self.master.iconphoto(False, PhotoImage(file=resource(r'assets\banana.ico')))
        self.master.resizable(width=False, height=False)
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        # while banana is listening, closing the window just sends it back to the tray
        if self.listening:
            self.master.withdraw()
        elif messagebox.askokcancel("Quit", "Do you want to quit?"):
            Actions.shutdown()

    def show(self):
        self.master.deiconify()
        self.master.lift()
        self.master.focus_force()

    def start_listening(self):
        self.master.withdraw()
        if self.listening:
            return
        self.listening = True
        GUI.tray = pystray.Icon('Banana', Image.open(banana), 'Banana', menu=pystray.Menu(
            pystray.MenuItem('Open Banana', lambda: self.master.after(0, self.show), default=True),
            pystray.MenuItem('Quit', lambda: self.master.after(0, Actions.shutdown)),
        ))
        GUI.tray.run_detached()
        threading.Thread(target=app.listen, daemon=True).start()

    def CreateWindow(self):

        js=load_settings()
        remote=events()
        master = self.master
        for child in master.winfo_children():
            child.destroy()

        self.bg = PhotoImage(file = resource(r'assets\banana.png'))
        label1 = Label( master, image = self.bg)
        label1.place(x = -10, y = -80)

        s=Style()
        s.configure('My.TFrame', background='black', highlightbackground="yellow",highlightthickness=5)
        s.configure('My2.TFrame', background='yellow', highlightbackground="black",highlightthickness=5)

        main1 = Frame(master, style='My2.TFrame')
        main1.pack(padx=50, pady=50)
        main = Frame(main1, style='My.TFrame')
        main.pack(padx=1, pady=1)
        textvariable=remote.getPath()
        if textvariable=="":
            textvariable="No path selected"
        cframe = Frame(main, style='My.TFrame')
        cframe.pack(pady=10, padx=10, side=TOP)

        a=tk.Checkbutton(cframe,
            text = js['settings']['start_notification']['title'],
            bg='black', fg='grey',
            variable=IntVar(value=js['settings']['start_notification']['enabled']),
            command=lambda:remote.changeNotifications(js, 'start_notification'),
            highlightbackground="yellow",
        )
        b=tk.Checkbutton(cframe,
            text = js['settings']['found_notification']['title'],
            bg='black', fg='grey',
            variable=IntVar(value=js['settings']['found_notification']['enabled']),
            command=lambda:remote.changeNotifications(js, 'found_notification'),
            highlightbackground="yellow",
        )
        c=tk.Checkbutton(cframe,
            text = js['settings']['debug_notification']['title'],
            bg='black', fg='grey',
            variable=IntVar(value=js['settings']['debug_notification']['enabled']),
            command=lambda:remote.changeNotifications(js, 'debug_notification'),
            highlightbackground="yellow",
        )
        d=tk.Checkbutton(cframe,
            text = js['settings']['setting_startup']['title'],
            bg='black', fg='grey',
            variable=IntVar(value=js['settings']['setting_startup']['enabled']),
            command=lambda:remote.changeNotifications(js, 'setting_startup'),
            highlightbackground="yellow",
        )
        e=tk.Checkbutton(cframe,
            text = js['settings']['start_on_launch']['title'],
            bg='black', fg='grey',
            variable=IntVar(value=js['settings']['start_on_launch']['enabled']),
            command=lambda:remote.changeNotifications(js, 'start_on_launch'),
            highlightbackground="yellow",
        )
        f2=tk.Checkbutton(cframe,
            text = js['settings']['blacklist_notifications']['title'],
            bg='black', fg='grey',
            variable=IntVar(value=js['settings']['blacklist_notifications']['enabled']),
            command=lambda:remote.changeNotifications(js, 'blacklist_notifications'),
            highlightbackground="yellow",
        )
        if js['settings']['start_notification']['enabled']==1:
            a.select()
        if js['settings']['found_notification']['enabled']==1:
            b.select()
        if js['settings']['debug_notification']['enabled']==1:
            c.select()
        if js['settings']['setting_startup']['enabled']==1:
            d.select()
        if js['settings']['start_on_launch']['enabled']==1:
            e.select()
        if js['settings']['blacklist_notifications']['enabled']==1:
            f2.select()
        a.pack()
        b.pack()
        c.pack()
        d.pack()
        # e.pack()
        # f2.pack()

        btn = tk.Button(main,text ='set path', bg='black', fg='yellow',command =lambda:remote.setNewPath(self))
        btn.pack(padx=5,pady=5,side=LEFT)
        if textvariable=="No path selected":
            label = tk.Label(main, text = textvariable, foreground='red', background='black')
            label.pack(padx=5,pady=5, side=RIGHT)
        else:
            label = tk.Label(main, text = textvariable, foreground='yellow', background='black')
            label.pack(padx=5,pady=5, side=RIGHT)
        if textvariable!="No path selected":
            if 'spotify' in str(textvariable).lower() and '.exe' in str(textvariable).lower():
                submit = tk.Button(main,text ='start', bg='black', fg='lime',command =lambda: remote.start(self))
                submit.pack(pady=5,side=RIGHT)
            elif not '.exe' in str(textvariable).lower():
                submit = tk.Button(main,text ='path to file needs to be a .exe', bg='black', fg='grey')
                submit.pack(pady=5,side=RIGHT)
            else:
                submit = tk.Button(main,text ='Invalid path, start anyway?', bg='black', fg='orange',command =lambda: remote.start(self))
                submit.pack(pady=5,side=RIGHT)
        elif textvariable=="No path selected":
            submit = tk.Button(main,text ='start', bg='black', fg='grey')
            submit.pack(pady=5,side=RIGHT)

try:
    main = app()
    main.main()
except KeyboardInterrupt:
    Actions.escape('KeyboardInterrupt. Closing.')
except Exception as e:
    Actions.escape('Banana Interrupted. Exception E.')
except:
    Actions.escape('Banana Closed.')

