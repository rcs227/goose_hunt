extends Node

# Store the Process ID of the external program
var external_pid: int = -1

func _ready() -> void:
	# Handle the close request manually so we can clean up first
	get_tree().set_auto_accept_quit(false)
	
	launch_external_app()

func launch_external_app() -> void:
	var godot_path = "res://test/test.exe"
	var global_path = ProjectSettings.globalize_path(godot_path)
	var arguments = ["--no-file"]
	
	# Open the app in the background and grab its unique PID
	external_pid = OS.create_process(global_path, arguments)
	
	if external_pid > 0:
		print("External app running with PID: ", external_pid)
	else:
		print("Failed to start external app.")

# This function intercepts Godot's shutdown event
func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_CLOSE_REQUEST:
		print("Game closing. Issuing taskkill command...")
		
		# Forcefully kill any process matching the executable name
		# /F means Force, /IM specifies the Image Name
		OS.execute("taskkill", ["/F", "/IM", "test.exe"], [], true)
		
		# Safely close your Godot game
		get_tree().quit()
