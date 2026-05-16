from pathlib import Path
from endstone.plugin import Plugin
from endstone_broadcaster.manager import BroadcasterManager

class BroadcasterPlugin(Plugin):
    api_version = "0.5"

    def __init__(self):
        super().__init__()
        self.mgr = None

    def on_enable(self):
        self.logger.info("starting broadcaster integration")
        
        self.mgr = BroadcasterManager(
            Path(self.data_folder),
            self.logger,
            "127.0.0.1",
            self.server.port
        )
        self.mgr.start()

    def on_disable(self):
        self.logger.info("shutting down broadcaster")
        if self.mgr:
            self.mgr.stop()
