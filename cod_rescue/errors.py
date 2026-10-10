"""Error taxonomy. Business-rule refusals are NOT exceptions: tools return them as results."""


class ExternalSourceError(Exception):
    """An authoritative source (inventory, prices, shipping rates, ledger) is unavailable.

    Never answered with a guess: callers hold the order (error_class TOOL_ERROR).
    """

    def __init__(self, source: str, message: str = ""):
        super().__init__(message or f"{source} source unavailable")
        self.source = source


class CommitTimeout(Exception):
    """The readiness commit may or may not have been applied (response lost).

    Never retried blindly: resolve via the operation ledger using the stable op_id.
    """

    def __init__(self, op_id: str):
        super().__init__(f"commit outcome unknown for {op_id}")
        self.op_id = op_id


class UnknownOrder(LookupError):
    pass
