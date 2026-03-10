from solana.rpc.api import Client
from solders.pubkey import Pubkey
import time
from dotenv import load_dotenv
load_dotenv()


RPC_URL = "https://mainnet.helius-rpc.com/?api-key=51cd6fd8-5960-4710-9dfd-ec3c1d1866fb"

client = Client(RPC_URL)


class OnChainAnalyzer:

    def get_top_holder_percent(self, token_address):

        try:
            token_pubkey = Pubkey.from_string(token_address)

            largest_accounts = client.get_token_largest_accounts(token_pubkey)
            supply = client.get_token_supply(token_pubkey)

            total_supply = float(supply.value.ui_amount)
            largest_holder = float(largest_accounts.value[0].amount.ui_amount)

            if total_supply == 0:
                return None

            percent = (largest_holder / total_supply) * 100

            return round(percent, 2)

        except Exception as e:
            print("On-chain error:", repr(e))
            return None
        

    def get_token_age_minutes(self, token_address):

        try:
            token_pubkey = Pubkey.from_string(token_address)

            # Get oldest transaction
            signatures = client.get_signatures_for_address(
                token_pubkey,
                limit=1000
            )

            if not signatures.value:
                return None

            # La plus ancienne est la dernière
            oldest_signature = signatures.value[-1]

            block_time = oldest_signature.block_time

            if block_time is None:
                return None

            current_time = int(time.time())

            age_seconds = current_time - block_time
            age_minutes = age_seconds / 60

            return round(age_minutes, 2)

        except Exception as e:
            print("Token age error:", repr(e))
            return None

    def check_mint_security(self, token_address):

        try:
            token_pubkey = Pubkey.from_string(token_address)

            account_info = client.get_account_info(token_pubkey)

            if not account_info.value:
                return None

            data = account_info.value.data

            # Mint account structure SPL:
            # bytes 0-32: mint authority option
            # bytes 36-68: freeze authority option

            mint_authority_disabled = data[0] == 0
            freeze_authority_disabled = data[36] == 0

            return {
                "mint_disabled": mint_authority_disabled,
                "freeze_disabled": freeze_authority_disabled
            }

        except Exception as e:
            print("Mint security error:", repr(e))
            return None      