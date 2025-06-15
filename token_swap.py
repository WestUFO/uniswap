"""
Uniswap UniversalRouter Token Swap Script
Выполняет свап токенов через Uniswap UniversalRouter с поддержкой v2/v3/v4 пулов
"""

import os
import json
from web3 import Web3
from eth_account import Account
from typing import Optional, Dict, Any
import requests
from decimal import Decimal


class UniswapSwapper:
    def __init__(self, private_key: str, rpc_url: str, chain_id: int = 1):
        """
        Инициализация свапера

        Args:
            private_key: Приватный ключ кошелька
            rpc_url: RPC URL для подключения к сети
            chain_id: ID сети (1 - Ethereum, 137 - Polygon, и т.д.)
        """
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.account = Account.from_key(private_key)
        self.chain_id = chain_id

        # Адреса контрактов (Ethereum Mainnet)
        self.contracts = {
            1: {  # Ethereum
                'universal_router': '0x3fC91A3afd70395Cd496C647d5a6CC9D4B2b7FAD',
                'permit2': '0x000000000022D473030F116dDEE9F6B43aC78BA3',
                'weth': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
            },
            137: {  # Polygon
                'universal_router': '0xec7BE89e9d109e7e3Fec59c222CF297125FEFda2',
                'permit2': '0x000000000022D473030F116dDEE9F6B43aC78BA3',
                'weth': '0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270'  # WMATIC
            }
        }

        # ABI для ERC20 токенов
        self.erc20_abi = [
            {
                "constant": True,
                "inputs": [],
                "name": "decimals",
                "outputs": [{"name": "", "type": "uint8"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [],
                "name": "symbol",
                "outputs": [{"name": "", "type": "string"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function"
            },
            {
                "constant": False,
                "inputs": [
                    {"name": "_spender", "type": "address"},
                    {"name": "_value", "type": "uint256"}
                ],
                "name": "approve",
                "outputs": [{"name": "", "type": "bool"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [
                    {"name": "_owner", "type": "address"},
                    {"name": "_spender", "type": "address"}
                ],
                "name": "allowance",
                "outputs": [{"name": "", "type": "uint256"}],
                "type": "function"
            }
        ]

        # Упрощенный ABI для UniversalRouter
        self.universal_router_abi = [
            {
                "inputs": [
                    {"name": "commands", "type": "bytes"},
                    {"name": "inputs", "type": "bytes[]"},
                    {"name": "deadline", "type": "uint256"}
                ],
                "name": "execute",
                "outputs": [],
                "stateMutability": "payable",
                "type": "function"
            }
        ]

    def get_token_info(self, token_address: str) -> Dict[str, Any]:
        """Получает информацию о токене"""
        contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=self.erc20_abi
        )

        try:
            symbol = contract.functions.symbol().call()
            decimals = contract.functions.decimals().call()
            balance = contract.functions.balanceOf(self.account.address).call()

            return {
                'symbol': symbol,
                'decimals': decimals,
                'balance': balance,
                'balance_formatted': balance / (10 ** decimals)
            }
        except Exception as e:
            print(f"Ошибка получения информации о токене {token_address}: {e}")
            return None

    def approve_token(self, token_address: str, amount: int) -> bool:
        """Одобряет токен для Permit2"""
        permit2_address = self.contracts[self.chain_id]['permit2']

        contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=self.erc20_abi
        )

        # Проверяем текущий allowance
        current_allowance = contract.functions.allowance(
            self.account.address,
            permit2_address
        ).call()

        if current_allowance >= amount:
            print(f"Токен уже одобрен с достаточной суммой: {current_allowance}")
            return True

        # Отправляем транзакцию на одобрение
        try:
            tx_data = contract.functions.approve(
                permit2_address,
                amount
            ).build_transaction({
                'from': self.account.address,
                'gas': 100000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(self.account.address)
            })

            signed_tx = self.account.sign_transaction(tx_data)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)

            print(f"Транзакция одобрения отправлена: {tx_hash.hex()}")
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)

            if receipt.status == 1:
                print("Токен успешно одобрен")
                return True
            else:
                print("Ошибка при одобрении токена")
                return False

        except Exception as e:
            print(f"Ошибка при одобрении токена: {e}")
            return False

    def get_quote(self, token_in: str, token_out: str, amount_in: str) -> Optional[Dict]:
        """
        Получает котировку для свапа через Uniswap API

        Args:
            token_in: Адрес входящего токена
            token_out: Адрес исходящего токена
            amount_in: Сумма входящего токена (в wei)
        """
        try:
            # Используем Uniswap Routing API
            url = "https://api.uniswap.org/v1/quote"
            params = {
                'tokenInAddress': token_in,
                'tokenOutAddress': token_out,
                'amount': amount_in,
                'type': 'exactIn',
                'protocols': 'v2,v3'
            }

            response = requests.get(url, params=params)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Ошибка получения котировки: {response.status_code}")
                return None

        except Exception as e:
            print(f"Ошибка при получении котировки: {e}")
            return None

    def build_swap_data(self, token_in: str, token_out: str, amount_in: int,
                        min_amount_out: int, recipient: str) -> tuple:
        """
        Создает данные для свапа через UniversalRouter
        Упрощенная версия - в реальности нужно использовать специальные библиотеки
        """

        # Команда для V3_SWAP_EXACT_IN (0x00)
        commands = "0x00"

        # Упрощенные входные данные (в реальности требуется более сложная логика)
        # Это пример структуры - для полной реализации используйте uniswap-universal-router-decoder
        swap_data = self.w3.eth.abi.encode(
            ['address', 'uint256', 'uint256', 'bytes', 'bool'],
            [
                recipient,  # получатель
                amount_in,  # сумма входящего токена
                min_amount_out,  # минимальная сумма исходящего токена
                b'',  # путь (упрощено)
                False  # unwrap WETH
            ]
        )

        return commands, [swap_data]

    def execute_swap(self, token_in_address: str, token_out_address: str,
                     amount_in_human: float, slippage: float = 0.5) -> bool:
        """
        Выполняет свап токенов

        Args:
            token_in_address: Адрес входящего токена
            token_out_address: Адрес исходящего токена
            amount_in_human: Сумма входящего токена (в человекочитаемом формате)
            slippage: Проскальзывание в процентах (по умолчанию 0.5%)
        """

        print(f"\n=== Начинаем свап ===")
        print(f"Входящий токен: {token_in_address}")
        print(f"Исходящий токен: {token_out_address}")
        print(f"Сумма: {amount_in_human}")
        print(f"Проскальзывание: {slippage}%")

        # Получаем информацию о токенах
        token_in_info = self.get_token_info(token_in_address)
        token_out_info = self.get_token_info(token_out_address)

        if not token_in_info or not token_out_info:
            print("Ошибка получения информации о токенах")
            return False

        print(f"\nВходящий токен: {token_in_info['symbol']} (баланс: {token_in_info['balance_formatted']:.6f})")
        print(f"Исходящий токен: {token_out_info['symbol']} (баланс: {token_out_info['balance_formatted']:.6f})")

        # Конвертируем сумму в wei
        amount_in_wei = int(amount_in_human * (10 ** token_in_info['decimals']))

        # Проверяем баланс
        if token_in_info['balance'] < amount_in_wei:
            print(f"Недостаточно токенов для свапа!")
            return False

        # Одобряем токен если необходимо
        if not self.approve_token(token_in_address, amount_in_wei):
            print("Не удалось одобрить токен")
            return False

        print("\n⚠️  ВНИМАНИЕ: Это упрощенная демонстрация!")
        print("Для реального свапа рекомендуется использовать:")
        print("1. uniswap-universal-router-decoder для правильного кодирования")
        print("2. Uniswap SDK для получения оптимальных путей")
        print("3. Тщательное тестирование на тестовых сетях")

        return True


def main():
    """Пример использования"""

    # Конфигурация (ВНИМАНИЕ: НЕ ИСПОЛЬЗУЙТЕ РЕАЛЬНЫЕ КЛЮЧИ В КОДЕ!)
    PRIVATE_KEY = "your_private_key_here"  # Замените на ваш приватный ключ
    RPC_URL = "https://eth-mainnet.g.alchemy.com/v2/your-api-key"  # Замените на ваш RPC

    # Примеры адресов токенов (Ethereum Mainnet)
    USDC = "0xA0b86a33E6441a8Bb614c0C9C9d8e6F5C41b34e5"
    WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"

    try:
        # Создаем экземпляр свапера
        swapper = UniswapSwapper(PRIVATE_KEY, RPC_URL, chain_id=1)

        # Выполняем свап
        success = swapper.execute_swap(
            token_in_address=USDC,  # Входящий токен
            token_out_address=WETH,  # Исходящий токен
            amount_in_human=100.0,  # Сумма (100 USDC)
            slippage=0.5  # 0.5% проскальзывание
        )

        if success:
            print("\n✅ Подготовка к свапу завершена успешно!")
        else:
            print("\n❌ Ошибка при подготовке свапа")

    except Exception as e:
        print(f"Критическая ошибка: {e}")


if __name__ == "__main__":
    main()
