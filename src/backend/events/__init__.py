from blinker import signal

# tenant specific
tenant_created = signal("tenant-created")
tenant_updated = signal("tenant-updated")
tenant_deleted = signal("tenant-deleted")

# task specific events
task_created = signal("task-created")
