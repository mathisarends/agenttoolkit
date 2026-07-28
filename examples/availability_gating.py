import asyncio
from dataclasses import dataclass

from agenttoolkit import ToolContext, Tools, provided, requires


@dataclass
class UserInfo:
    name: str
    is_admin: bool = False


tools = Tools()


# Hidden entirely unless a UserInfo dependency is present in the context.
@tools.action("Get personalized settings", available_when=provided(UserInfo))
def get_settings() -> str:
    return "settings"


# Hidden unless a UserInfo is present AND satisfies the predicate. `~`, `&`
# and `|` combine ToolAvailability instances, e.g. `requires(...) & provided(...)`.
@tools.action(
    "Delete a user account (admin only)",
    available_when=requires(UserInfo, predicate=lambda user: user.is_admin),
)
def delete_account() -> str:
    return "account deleted"


async def main() -> None:
    print("no context:", [tool.name for tool in tools.available()])

    tools.set_context(ToolContext(UserInfo(name="Mathis")))
    print("regular user:", [tool.name for tool in tools.available()])

    tools.set_context(ToolContext(UserInfo(name="Mathis", is_admin=True)))
    print("admin:", [tool.name for tool in tools.available()])


if __name__ == "__main__":
    asyncio.run(main())
