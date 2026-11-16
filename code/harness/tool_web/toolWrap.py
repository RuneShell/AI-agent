


class ToolWrap:
    _monitor = None

    def __init__(self, monitor):
        self._monitor = monitor

    # monitor
    def update_dashboard_widget(self, name, widget):
        self._monitor.update_dashboard_widget(name, widget)

