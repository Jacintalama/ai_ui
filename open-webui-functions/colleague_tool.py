"""Ask a colleague.

This body is never executed. The tasks service intercepts `ask_colleague`
by name inside execute_tool_call and runs the handoff itself, because this
row is editable from the web UI and a depth cap somebody can edit away is
not a depth cap.

The row exists because a tool without a generated spec is invisible to every
model. What matters here is the signature and the docstring: that is what
becomes the spec the model reads.
"""


class Tools:
    def __init__(self):
        pass

    async def ask_colleague(self, agent: str, question: str) -> str:
        """
        Ask one of your colleagues something you cannot answer yourself.

        Use this when the job in front of you needs something that is
        plainly somebody else's: a file you cannot see, a calendar you do
        not keep, an app you did not build. Ask them for that one thing,
        then carry on and finish your own answer with what they say.

        Do not use it to pass the whole question on, and do not use it to
        chat. If you can answer, answer.

        :param agent: The colleague's name, exactly as it appears in your
            roster, for example "Iris".
        :param question: The one thing you need from them, in a sentence.
        """
        return ("This tool is handled by the platform and was not run here.")
