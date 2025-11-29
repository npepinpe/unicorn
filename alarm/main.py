import gc
import time
import network
import rp2
import SECRETS
import machine
import asyncio
gc.collect()

from machine import Timer
from stellar import StellarUnicorn
from picographics import PicoGraphics, DISPLAY_STELLAR_UNICORN as DISPLAY
gc.collect()

from simple import MQTTClient
from audio import WavPlayer
gc.collect()

# Global debug logging
DEBUG = True

# Set up graphics and other outputs
su = StellarUnicorn()
graphics = PicoGraphics(DISPLAY)
width = StellarUnicorn.WIDTH
height = StellarUnicorn.HEIGHT
sound = WavPlayer()
wlan = network.WLAN(network.STA_IF)
loop = asyncio.get_event_loop()
mqtt = MQTTClient("unicorn", SECRETS.MQTT_HOST, port=SECRETS.MQTT_PORT, user=SECRETS.MQTT_USER, password=SECRETS.MQTT_PASSWORD)
mqtt.DEBUG = DEBUG
rp2.country('DE')

# Colors
white = graphics.create_pen(255,255,255)
black = graphics.create_pen(0,0,0)
red = graphics.create_pen(255,0,0)
green = graphics.create_pen(0,255,0)
blue = graphics.create_pen(0,0,255)
gray = graphics.create_pen(20,20,20)
light_gray = graphics.create_pen(80,80,150)
colors = [ red, black ]

# Useful coordinates
topLeft = (0,0)
topRight = (width,0)
bottomLeft = (0, height)
bottomRight = (width,height)

# Network helpers
network_statuses = {
    0: 'Link is down',
    1: 'Connected to wifi',
    2: 'Connected to wifi, but no IP address',
    3: 'Connected to wifi with an IP address',
    -1: 'Connection failed',
    -2: 'No matching SSID found (could be out of range, or down)',
    -3: 'Authentication failure'
}

# We have to redraw every frame logically, so we keep the state of each
# section to be drawn in a separate entity, and then draw them all outlined
# in a single method
wifi_indicator = False
mqtt_indicator = False
alarmed = False
rooms = {
    b'office':  [(0,0),(3,6),False,0,0], # [(x,y),(width,height),Alarmed,flash_ticks,flash_color]
    b'ebath':   [(4,0),(1,6),False,0,0],
    b'kitchen': [(6,0),(2,6),False,0,0],
    b'living':  [(0,9),(4,7),False,0,0],
    b'dining':  [(5,9),(3,7),False,0,0],
    b'bedroom': [(9,10),(2,6),False,0,0],
    b'bbath':   [(12,10),(1,6),False,0,0],
    b'baby':    [(14,9),(2,7),False,0,0]
}

# Map of the house, drawn once for the walls. Rooms are painted over for each
# frame afterwards
house = [
  [0,0,0,1,0,1,0,0,1,0,0,0,0,0,0,0],
  [0,0,0,1,0,1,0,0,1,0,0,0,0,0,0,0],
  [0,0,0,1,0,1,0,0,1,0,0,0,0,0,0,0],
  [0,0,0,1,0,1,0,0,1,0,0,0,0,0,0,0],
  [0,0,0,1,0,1,0,0,1,0,0,0,0,0,0,0],
  [0,0,0,1,0,1,0,0,1,0,0,0,0,0,0,0],
  [1,1,2,1,2,1,2,1,1,0,0,0,0,0,0,0],
  [1,1,2,2,2,2,2,2,1,0,0,0,0,0,0,0],
  [1,1,2,1,1,1,1,2,1,1,1,1,1,1,1,1],
  [0,0,0,0,1,0,0,0,2,2,2,2,2,2,0,0],
  [0,0,0,0,1,0,0,0,1,0,0,1,0,1,0,0],
  [0,0,0,0,1,0,0,0,1,0,0,1,0,1,0,0],
  [0,0,0,0,1,0,0,0,1,0,0,1,0,1,0,0],
  [0,0,0,0,1,0,0,0,1,0,0,1,0,1,0,0],
  [0,0,0,0,1,0,0,0,1,0,0,1,0,1,0,0],
  [0,0,0,0,1,0,0,0,1,0,0,1,0,1,0,0],
]

# Graphics programming
def clear(g):
    g.set_pen(black)
    g.clear()

def draw(g, x, y, color):
    g.set_pen(color)
    g.pixel(x, y)

def fill(g, start, end, color):
    _set_pen = g.set_pen
    _pixel = g.pixel

    for x in range(start[0], end[0]):
        for y in range(start[1], end[1]):
            _set_pen(color)
            _pixel(x, y)

# Debug output/indicators
def draw_wifi_indicator(g, status):
    g.set_pen(green if status else red)
    g.pixel(width-3, 0)

def draw_mqtt_indicator(g, status):
    g.set_pen(green if status else red)
    g.pixel(width-2, 0)

def draw_debug_indicator(g, status):
    g.set_pen(green if status else blue)
    g.pixel(width-1, 0)

def draw_house(g):
    _set_pen = g.set_pen
    _pixel = g.pixel

    for row in range(0,16):
        for col in range(0,16):
            color = house[row][col]
            if color == 0:
                _set_pen(black)
            elif color == 1:
                _set_pen(gray)
            else:
                _set_pen(light_gray)
            
            _pixel(col, row)

def draw_state(g):
    global wifi_indicator
    global mqtt_indicator
    global DEBUG

    draw_wifi_indicator(g, wifi_indicator)
    draw_mqtt_indicator(g, mqtt_indicator)
    draw_debug_indicator(g, DEBUG)
    for state in rooms.values():
        start_x, start_y = state[0]
        end_x, end_y = state[1]
        if state[2]:
            now = time.ticks_ms()
            elapsed = time.ticks_ms() - state[3]
            if now - state[3] > 250:
                state[4] = state[4] ^ 1
                g.set_pen(black if state[4] == 0 else red)
                state[3] = now
        else:
            g.set_pen(black)
        g.rectangle(start_x, start_y, end_x, end_y)

def connect_wlan():
    wlan.active(True)
    wlan.config(pm = 0xa11140, hostname = 'unicorn', trace=1 if DEBUG else 0)
    wlan.connect(SECRETS.SSID, SECRETS.PASSWORD)

def disconnect_wlan():
    wlan.disconnect()
    wlan.active(False)
    wlan.deinit()

def handle_message(topic, msg):
    global alarmed
    global rooms

    dprint('Received mqtt message [%s] on [%s]' % (msg, topic))
    room = rooms[msg]
    if msg in rooms:
        rooms[msg][2] = True
        alarmed = True

def acknowledge_alarm():
    global alarmed
    global sound

    dprint('Acknowledged alert')
    alarmed = False
    sound.stop()
    for room in rooms.values():
        room[2] = False
        room[3] = 0
        room[4] = 0

# Debug function to monitor the RAM usage
def report_memory():
    gc.collect()
    dprint("RAM free %d alloc %d" % (gc.mem_free(), gc.mem_alloc()))

def dprint(msg):
    if DEBUG:
        print(msg)

# Tasks
async def ensure_wifi_connected():
    global wifi_indicator

    while True:
        if wlan.status() == 3:
            wifi_indicator = True
            await asyncio.sleep(1)
            continue
        
        dprint('WLAN not connected, reconnecting...')
        wifi_indicator = False
        while not wlan.isconnected():
            disconnect_wlan()
            await asyncio.sleep(1)

            connect_wlan()
            start = time.ticks_ms()
            while not wlan.isconnected() and time.ticks_ms() - start < 300000:
                await asyncio.sleep(1)

            dprint('WLAN status = %s' % network_statuses[wlan.status()])
            gc.collect()

async def check_mqtt_messages():
    global mqtt_indicator
    
    while True:
        if not wlan.isconnected():
            mqtt_indicator = False
            await asyncio.sleep(1)
            continue

        try:
            if not mqtt_indicator:
                if not mqtt.connect(clean_session=False):
                    dprint('New MQTT session set up, listening to topic [unicorn_alarm]')
                    mqtt.subscribe(b"unicorn_alarm")

            mqtt.ping()
            mqtt_indicator = True
            # dprint('Checking MQTT messages...')
            mqtt.check_msg()
        except OSError as e:
            dprint('Failed to check for mqtt message [%s]' % e)
            mqtt_indicator = False

        gc.collect()
        await asyncio.sleep_ms(100)

async def draw_loop():
    global DEBUG
    
    while True:
        # Allow adjusting the brightness for weaklings
        if su.is_pressed(StellarUnicorn.SWITCH_BRIGHTNESS_UP):
            su.adjust_brightness(+0.01)

        if su.is_pressed(StellarUnicorn.SWITCH_BRIGHTNESS_DOWN):
            su.adjust_brightness(-0.01)

        # Allow adjusting the volume for weaklings
        # if su.is_pressed(StellarUnicorn.SWITCH_VOLUME_UP):
            # do nothing for now

        # if su.is_pressed(StellarUnicorn.SWITCH_VOLUME_DOWN):
            # do nothing for now

        if alarmed:
            if su.is_pressed(StellarUnicorn.SWITCH_A):
                acknowledge_alarm()
            elif not sound.is_playing():
                sound.play("beepboop.wav")

        # Toggle on/off debug logging
        if su.is_pressed(StellarUnicorn.SWITCH_D):
            DEBUG = False if DEBUG else True
            dprint('Toggled debug logging')

        # Update the state before going back to sleep
        draw_state(graphics)
        su.update(graphics)

        # pause for a moment (important or the USB serial device will fail)
        gc.collect()
        await asyncio.sleep_ms(10)

async def main():
    asyncio.create_task(ensure_wifi_connected())
    asyncio.create_task(check_mqtt_messages())
    asyncio.create_task(draw_loop())

    while True:
        await asyncio.sleep(10)

# Initialization and other stuff
graphics.set_pen(black)
graphics.clear()
su.update(graphics)

# Draw the house map only once to draw walls and corridors,
# then never again; draw the dynamic elements too once just to
# initialize them as well
draw_house(graphics)
draw_state(graphics)
su.update(graphics)
report_memory()

report_memory()
mqtt.set_callback(handle_message)
asyncio.run(main())
