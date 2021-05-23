from typing import Callable, Dict, List

from chia.harvester.harvester import Harvester
from chia.protocols.farmer_protocol import FarmingInfo
from chia.util.ws_message import WsRpcMessage, create_payload_dict


class HarvesterRpcApi:
    def __init__(self, harvester: Harvester):
        self.service = harvester
        self.service_name = "chia_harvester"

    def get_routes(self) -> Dict[str, Callable]:
        return {
            "/get_plots": self.get_plots,
            "/refresh_plots": self.refresh_plots,
            "/delete_plot": self.delete_plot,
            "/add_plot_directory": self.add_plot_directory,
            "/get_plot_directories": self.get_plot_directories,
            "/remove_plot_directory": self.remove_plot_directory,
            "/add_user": self.add_user,
            "/get_user": self.get_user,
            "/logout": self.logout,
            "/logged_in": self.logged_in,
            "/account_info": self.account_info,
        }

    async def account_info(self, request: Dict):
        account_info = await self.service.get_account_info()
        return account_info

    async def add_user(self, request: Dict) -> Dict:
        status = await self.service.add_user(request)
        return {
            "added": status,
        }

    async def logout(self, request: Dict) -> Dict:
        request = {"username": None, "password": None}
        await self.service.remove_user(request)
        return {
            "success": True,
        }

    async def get_user(self, request: Dict) -> Dict:
        username = self.service.username

        return {
            "username": username,
        }

    async def logged_in(self, request: Dict) -> Dict:
        if not self.service.logged_in:
            logged_in = await self.service.get_logged_in()
        else:
            logged_in = self.service.logged_in
        return {
            "logged_in": logged_in,
        }

    async def _state_changed(self, change: str, state=None) -> List[WsRpcMessage]:
        if change == "plots":
            data = await self.get_plots({})
            payload = create_payload_dict("get_plots", data, self.service_name, "wallet_ui")
            return [payload]
        if change == "farming_info":
            state: FarmingInfo = state
            data = state.to_json_dict()
            payload = create_payload_dict(
                "farming_info",
                data,
                self.service_name,
                "wallet_ui",
            )
            return [payload]
        return []

    async def get_plots(self, request: Dict) -> Dict:
        plots, failed_to_open, not_found = self.service.get_plots()
        return {
            "plots": plots,
            "failed_to_open_filenames": failed_to_open,
            "not_found_filenames": not_found,
        }

    async def refresh_plots(self, request: Dict) -> Dict:
        await self.service.refresh_plots()
        return {}

    async def delete_plot(self, request: Dict) -> Dict:
        filename = request["filename"]
        if self.service.delete_plot(filename):
            return {}
        raise ValueError(f"Not able to delete file {filename}")

    async def add_plot_directory(self, request: Dict) -> Dict:
        directory_name = request["dirname"]
        if await self.service.add_plot_directory(directory_name):
            return {}
        raise ValueError(f"Did not add plot directory {directory_name}")

    async def get_plot_directories(self, request: Dict) -> Dict:
        plot_dirs = await self.service.get_plot_directories()
        return {"directories": plot_dirs}

    async def remove_plot_directory(self, request: Dict) -> Dict:
        directory_name = request["dirname"]
        if await self.service.remove_plot_directory(directory_name):
            return {}
        raise ValueError(f"Did not remove plot directory {directory_name}")
