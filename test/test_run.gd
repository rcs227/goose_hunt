extends Node2D

var godot_path = "res://test/test.exe"
var global_path = ProjectSettings.globalize_path(godot_path)
var arguments = ["--no-file"]
var output = []
var blocking = true

# Called when the node enters the scene tree for the first time.
func _ready() -> void:
	OS.execute(global_path, arguments, output, blocking)
