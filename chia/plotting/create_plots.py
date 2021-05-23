import asyncio
import logging
from datetime import datetime
from pathlib import Path
from secrets import token_bytes
from typing import List, Optional, Tuple, Any

import aiohttp
from blspy import AugSchemeMPL, G1Element, PrivateKey
from chiapos import DiskPlotter

from chia.plotting.plot_tools import (
    add_plot_directory,
    stream_plot_info_ph,
    stream_plot_info_pk,
)
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import decode_puzzle_hash
from chia.util.config import config_path_for_filename, load_config
from chia.util.keychain import Keychain
from chia.util.path import mkdir
from chia.wallet.derive_keys import (
    master_sk_to_farmer_sk,
    master_sk_to_local_sk,
    master_sk_to_pool_sk,
)

log = logging.getLogger(__name__)


def get_farmer_public_key(alt_fingerprint: Optional[int] = None) -> G1Element:
    sk_ent: Optional[Tuple[PrivateKey, bytes]]
    keychain: Keychain = Keychain()
    if alt_fingerprint is not None:
        sk_ent = keychain.get_private_key_by_fingerprint(alt_fingerprint)
    else:
        sk_ent = keychain.get_first_private_key()
    if sk_ent is None:
        raise RuntimeError("No keys, please run 'chia keys add', 'chia keys generate' or provide a public key with -f")
    return master_sk_to_farmer_sk(sk_ent[0]).get_g1()


def get_pool_public_key(alt_fingerprint: Optional[int] = None) -> G1Element:
    sk_ent: Optional[Tuple[PrivateKey, bytes]]
    keychain: Keychain = Keychain()
    if alt_fingerprint is not None:
        sk_ent = keychain.get_private_key_by_fingerprint(alt_fingerprint)
    else:
        sk_ent = keychain.get_first_private_key()
    if sk_ent is None:
        raise RuntimeError("No keys, please run 'chia keys add', 'chia keys generate' or provide a public key with -p")
    return master_sk_to_pool_sk(sk_ent[0]).get_g1()


async def post(session: aiohttp.ClientSession, url: str, data: Any):
    response = await session.post(url, json=data)
    if response.status == 200:
        return await response.json()


async def send_update(api_url, user_name, password, plot_id, status):
    cookie_jar = aiohttp.CookieJar(unsafe=True)
    session = aiohttp.ClientSession(cookie_jar=cookie_jar)
    sign_in_data = {"email": user_name, "password": password}
    response_auth = await post(session, f"{api_url}/sign_in", sign_in_data)
    success_auth = response_auth["success"]
    assert success_auth
    data = {"plot_id": plot_id.hex(), "plotting_status": status}
    response = await post(session, f"{api_url}/plotting_update", data)
    success = response["success"]
    await session.close()
    return success


def create_plots(args, root_path, use_datetime=True, test_private_keys: Optional[List] = None):
    config_filename = config_path_for_filename(root_path, "config.yaml")
    config = load_config(root_path, config_filename)
    pool_pub_hex = config["pool_public_key"]
    farmer_pub_hex = config["farmer_public_key"]

    if args.tmp2_dir is None:
        args.tmp2_dir = args.tmp_dir
    pool_contract_puzzle_hash = None
    farmer_public_key = G1Element.from_bytes(bytes.fromhex(farmer_pub_hex))
    pool_public_key = G1Element.from_bytes(bytes.fromhex(pool_pub_hex))
    # pool_public_key = G1Element.from_bytes(bytes.fromhex(args.pool_public_key))
    # farmer_public_key = G1Element.from_bytes(bytes.fromhex(args.farmer_public_key))
    num = args.num

    if args.size < config["min_mainnet_k_size"] and test_private_keys is None:
        log.warning(f"Creating plots with size k={args.size}, which is less than the minimum required for mainnet")
    if args.size < 22:
        log.warning("k under 22 is not supported. Increasing k to 22")
        args.size = 22

    log.info(
        f"Creating {num} plots of size {args.size}, pool public key:  "
        f"{bytes(pool_public_key).hex()} farmer public key: {bytes(farmer_public_key).hex()}"
    )

    tmp_dir_created = False
    if not args.tmp_dir.exists():
        mkdir(args.tmp_dir)
        tmp_dir_created = True

    tmp2_dir_created = False
    if not args.tmp2_dir.exists():
        mkdir(args.tmp2_dir)
        tmp2_dir_created = True

    mkdir(args.final_dir)

    finished_filenames = []
    for i in range(num):
        # Generate a random master secret key
        if test_private_keys is not None:
            assert len(test_private_keys) == num
            sk: PrivateKey = test_private_keys[i]
        else:
            sk = AugSchemeMPL.key_gen(token_bytes(32))

        # The plot public key is the combination of the harvester and farmer keys
        plot_public_key = ProofOfSpace.generate_plot_public_key(master_sk_to_local_sk(sk).get_g1(), farmer_public_key)

        # The plot id is based on the harvester, farmer, and pool keys
        plot_id: bytes32 = ProofOfSpace.calculate_plot_id_pk(pool_public_key, plot_public_key)
        plot_memo: bytes32 = stream_plot_info_pk(pool_public_key, farmer_public_key, sk)

        u_config = load_config(root_path, config_filename)
        username = u_config["harvester"]["username"]
        password = u_config["harvester"]["password"]
        api_url = u_config["harvester"]["api_url"]
        if username is not None and password is not None:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(send_update(api_url, username, password, plot_id, 0))

        if args.plotid is not None:
            log.info(f"Debug plot ID: {args.plotid}")
            plot_id = bytes32(bytes.fromhex(args.plotid))

        if args.memo is not None:
            log.info(f"Debug memo: {args.memo}")
            plot_memo = bytes.fromhex(args.memo)

        # Uncomment next two lines if memo is needed for dev debug
        plot_memo_str: str = plot_memo.hex()
        log.info(f"Memo: {plot_memo_str}")

        dt_string = datetime.now().strftime("%Y-%m-%d-%H-%M")

        if use_datetime:
            filename: str = f"plot-k{args.size}-{dt_string}-{plot_id}.plot"
        else:
            filename = f"plot-k{args.size}-{plot_id}.plot"
        full_path: Path = args.final_dir / filename

        resolved_final_dir: str = str(Path(args.final_dir).resolve())
        plot_directories_list: str = config["harvester"]["plot_directories"]

        if args.exclude_final_dir:
            log.info(f"NOT adding directory {resolved_final_dir} to harvester for farming")
            if resolved_final_dir in plot_directories_list:
                log.warning(f"Directory {resolved_final_dir} already exists for harvester, please remove it manually")
        else:
            if resolved_final_dir not in plot_directories_list:
                # Adds the directory to the plot directories if it is not present
                log.info(f"Adding directory {resolved_final_dir} to harvester for farming")
                config = add_plot_directory(resolved_final_dir, root_path)

        if not full_path.exists():
            log.info(f"Starting plot {i + 1}/{num}")
            # Creates the plot. This will take a long time for larger plots.
            plotter: DiskPlotter = DiskPlotter()
            plotter.create_plot_disk(
                str(args.tmp_dir),
                str(args.tmp2_dir),
                str(args.final_dir),
                filename,
                args.size,
                plot_memo,
                plot_id,
                args.buffer,
                args.buckets,
                args.stripe_size,
                args.num_threads,
                args.nobitfield,
            )
            finished_filenames.append(filename)
            u_config = load_config(root_path, config_filename)
            username = u_config["harvester"]["username"]
            password = u_config["harvester"]["password"]
            api_url = u_config["harvester"]["api_url"]
            if username is not None and password is not None:
                loop = asyncio.get_event_loop()
                loop.run_until_complete(send_update(api_url, username, password, plot_id, 1))
        else:
            log.info(f"Plot {filename} already exists")

    log.info("Summary:")

    if tmp_dir_created:
        try:
            args.tmp_dir.rmdir()
        except Exception:
            log.info(f"warning: did not remove primary temporary folder {args.tmp_dir}, it may not be empty.")

    if tmp2_dir_created:
        try:
            args.tmp2_dir.rmdir()
        except Exception:
            log.info(f"warning: did not remove secondary temporary folder {args.tmp2_dir}, it may not be empty.")

    log.info(f"Created a total of {len(finished_filenames)} new plots")
    for filename in finished_filenames:
        log.info(filename)
