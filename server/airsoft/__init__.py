"""Airsoft control point server: MQTT bridge, game modes, dashboard, audio.

Layout:
  config.py     constants shared by everything (versions, ports, box names)
  hub.py        shared runtime state: boxes, the game dict, SSE broadcast,
                and publishing the game state to boxes and browsers
  boxes.py      turning box MQTT messages into box state
  connmon.py    connection monitoring (drops, reboots, weak signal, log)
  bridge.py     the MQTT client loop
  auth.py       referee PIN login
  clock.py      the game clock loop that ticks every mode
  modes/        one module per game mode (domination, rush, ...)
  web.py        Flask routes and pages
"""
