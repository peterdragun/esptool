# This file includes the operations with eFuses for ESP32 chip
#
# SPDX-FileCopyrightText: 2020-2025 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: GPL-2.0-or-later

import rich_click as click

import espsecure

import esptool

from .mem_definition import EfuseDefineBlocks
from .. import util
from ..base_operations import (
    BaseCommands,
    NonCompositeTuple,
    TupleParameter,
    add_force_write_always,
    add_show_sensitive_info_option,
)


class Esp32Commands(BaseCommands):
    ################################### CLI definitions ###################################

    def add_cli_commands(self, cli: click.Group):
        super().add_cli_commands(cli)
        blocks_for_keys = EfuseDefineBlocks().get_blocks_for_keys()

        @cli.command(
            "burn-key",
            help="Burn a 256-bit key to EFUSE. Arguments are pairs of block name and "
            "key file, containing 256 bits of binary key data.\n\n"
            f"Block is one of: [{', '.join(blocks_for_keys)}]",
        )
        @click.argument(
            "block_keyfile",
            metavar="<BLOCK> <KEYFILE>",
            cls=TupleParameter,
            required=True,
            nargs=-1,
            max_arity=len(blocks_for_keys),
            type=NonCompositeTuple([click.Choice(blocks_for_keys), click.File("rb")]),
        )
        @click.option(
            "--no-protect-key",
            is_flag=True,
            help="Disable default read- and write-protecting of the key. "
            "If this option is not set, once the key is flashed "
            "it cannot be read back or changed.",
        )
        @add_force_write_always
        @add_show_sensitive_info_option
        @click.pass_context
        def burn_key_cli(
            ctx, block_keyfile, no_protect_key, show_sensitive_info, **kwargs
        ):
            block, keyfile = zip(*block_keyfile)
            show_sensitive_info = ctx.show_sensitive_info
            self.burn_key(block, keyfile, no_protect_key, show_sensitive_info)

        @cli.command(
            "burn-key-digest",
            short_help="Parse a RSA public key and burn the digest.",
            help="Parse a RSA public key and burn the digest to eFuse for use with Secure Boot V2.",
        )
        @click.argument("keyfile", type=click.File("rb"))
        @click.option(
            "--no-protect-key",
            is_flag=True,
            help="Disable default write-protecting of the key digest. "
            "If this option is not set, once the key is flashed it cannot be changed.",
        )
        @add_force_write_always
        @add_show_sensitive_info_option
        @click.pass_context
        def burn_key_digest_cli(
            ctx, keyfile, no_protect_key, show_sensitive_info, **kwargs
        ):
            kwargs["show_sensitive_info"] = ctx.show_sensitive_info
            self.burn_key_digest(
                ctx.obj["esp"], keyfile, no_protect_key, show_sensitive_info
            )

        @cli.command(
            "set-flash-voltage",
            short_help="Permanently set the internal flash voltage regulator.",
        )
        @click.argument("voltage", type=click.Choice(["1.8V", "3.3V", "OFF"]))
        def set_flash_voltage_cli(voltage):
            """Permanently set the internal flash voltage regulator to either 1.8V, 3.3V or OFF.
            This means GPIO12 can be high or low at reset without changing the flash voltage."""
            self.set_flash_voltage(voltage)

    ###################################### Commands ######################################

    def get_custom_mac(self):
        version = self.efuses["MAC_VERSION"].get()
        if version > 0:
            print(
                f"Custom MAC Address version {version}: {self.efuses['CUSTOM_MAC'].get()}"
            )
        else:
            print("Custom MAC Address is not set in the device.")

    def set_flash_voltage(self, voltage):
        sdio_force = self.efuses["XPD_SDIO_FORCE"]
        sdio_tieh = self.efuses["XPD_SDIO_TIEH"]
        sdio_reg = self.efuses["XPD_SDIO_REG"]

        # check efuses aren't burned in a way which makes this impossible
        if voltage == "OFF" and sdio_reg.get() != 0:
            raise esptool.FatalError(
                "Can't set flash regulator to OFF as XPD_SDIO_REG eFuse is already burned"
            )

        if voltage == "1.8V" and sdio_tieh.get() != 0:
            raise esptool.FatalError(
                "Can't set regulator to 1.8V is XPD_SDIO_TIEH eFuse is already burned"
            )

        if voltage == "OFF":
            msg = "Disable internal flash voltage regulator (VDD_SDIO). "
            "SPI flash will need to be powered from an external source.\n"
            "The following eFuse is burned: XPD_SDIO_FORCE.\n"
            "It is possible to later re-enable the internal regulator"
            "to 3.3V" if sdio_tieh.get() != 0 else "to 1.8V or 3.3V"
            "by burning an additional eFuse"
        elif voltage == "1.8V":
            msg = "Set internal flash voltage regulator (VDD_SDIO) to 1.8V.\n"
            "The following eFuses are burned: XPD_SDIO_FORCE, XPD_SDIO_REG.\n"
            "It is possible to later increase the voltage to 3.3V (permanently) "
            "by burning additional eFuse XPD_SDIO_TIEH"
        elif voltage == "3.3V":
            msg = "Enable internal flash voltage regulator (VDD_SDIO) to 3.3V.\n"
            "The following eFuses are burned: XPD_SDIO_FORCE, XPD_SDIO_REG, XPD_SDIO_TIEH."
        print(msg)
        sdio_force.save(1)  # Disable GPIO12
        if voltage != "OFF":
            sdio_reg.save(1)  # Enable internal regulator
        if voltage == "3.3V":
            sdio_tieh.save(1)
        print("VDD_SDIO setting complete.")
        if not self.efuses.burn_all(check_batch_mode=True):
            return
        print("Successful")

    def adc_info(self):
        adc_vref = self.efuses["ADC_VREF"]
        blk3_reserve = self.efuses["BLK3_PART_RESERVE"]

        vref_raw = adc_vref.get_raw()
        if vref_raw == 0:
            print("ADC VRef calibration: None (1100mV nominal)")
        else:
            print(f"ADC VRef calibration: {adc_vref.get()}mV")

        if blk3_reserve.get():
            print("ADC readings stored in eFuse BLOCK3:")
            print(f"    ADC1 Low reading  (150mV): {self.efuses['ADC1_TP_LOW'].get()}")
            print(f"    ADC1 High reading (850mV): {self.efuses['ADC1_TP_HIGH'].get()}")
            print(f"    ADC2 Low reading  (150mV): {self.efuses['ADC2_TP_LOW'].get()}")
            print(f"    ADC2 High reading (850mV): {self.efuses['ADC2_TP_HIGH'].get()}")

    def burn_key(self, block, keyfile, no_protect_key, show_sensitive_info):
        datafile_list = keyfile[
            0 : len([keyfile for keyfile in keyfile if keyfile is not None]) :
        ]
        block_name_list = block[
            0 : len([block for block in block if block is not None]) :
        ]

        util.check_duplicate_name_in_list(block_name_list)
        if len(block_name_list) != len(datafile_list):
            raise esptool.FatalError(
                "The number of blocks (%d) and datafile (%d) should be the same."
                % (len(block_name_list), len(datafile_list))
            )

        print("Burn keys to blocks:")
        for block_name, datafile in zip(block_name_list, datafile_list):
            efuse = None
            for block in self.efuses.blocks:
                if block_name == block.name or block_name in block.alias:
                    efuse = self.efuses[block.name]
            if efuse is None:
                raise esptool.FatalError("Unknown block name - %s" % (block_name))
            num_bytes = efuse.bit_len // 8
            data = datafile.read()
            datafile.close()
            revers_msg = None
            if block_name in ("flash_encryption", "secure_boot_v1"):
                revers_msg = "\tReversing the byte order"
                data = data[::-1]
            print(" - %s" % (efuse.name), end=" ")
            print(
                "-> [{}]".format(
                    util.hexify(data, " ")
                    if show_sensitive_info
                    else " ".join(["??"] * len(data))
                )
            )
            if revers_msg:
                print(revers_msg)
            if len(data) != num_bytes:
                raise esptool.FatalError(
                    "Incorrect key file size %d. "
                    "Key file must be %d bytes (%d bits) of raw binary key data."
                    % (len(data), num_bytes, num_bytes * 8)
                )

            efuse.save(data)

            if block_name in ("flash_encryption", "secure_boot_v1"):
                if not no_protect_key:
                    print("\tDisabling read to key block")
                    efuse.disable_read()

            if not no_protect_key:
                print("\tDisabling write to key block")
                efuse.disable_write()
            print("")

        if no_protect_key:
            print("Key is left unprotected as per --no-protect-key argument.")

        msg = "Burn keys in eFuse blocks.\n"
        if no_protect_key:
            msg += (
                "The key block will be left readable and writeable "
                "(due to --no-protect-key)"
            )
        else:
            msg += (
                "The key block will be read and write protected "
                "(no further changes or readback)"
            )
        print(msg, "\n")
        if not self.efuses.burn_all(check_batch_mode=True):
            return
        print("Successful")

    def burn_key_digest(self, esp, keyfile, no_protect_key, show_sensitive_info):
        if self.efuses.coding_scheme == self.efuses.REGS.CODING_SCHEME_34:
            raise esptool.FatalError(
                "burn_key_digest only works with 'None' coding scheme"
            )

        chip_revision = esp.get_chip_revision()
        if chip_revision < 300:
            raise esptool.FatalError(
                "Incorrect chip revision for Secure boot v2. "
                "Detected: v%d.%d. Expected: >= v3.0"
                % (chip_revision / 100, chip_revision % 100)
            )

        digest = espsecure._digest_sbv2_public_key(keyfile)
        efuse = self.efuses["BLOCK2"]
        num_bytes = efuse.bit_len // 8
        if len(digest) != num_bytes:
            raise esptool.FatalError(
                "Incorrect digest size %d. "
                "Digest must be %d bytes (%d bits) of raw binary key data."
                % (len(digest), num_bytes, num_bytes * 8)
            )
        print(" - %s" % (efuse.name), end=" ")
        print(
            "-> [{}]".format(
                util.hexify(digest, " ")
                if show_sensitive_info
                else " ".join(["??"] * len(digest))
            )
        )

        efuse.save(digest)
        if not no_protect_key:
            print("Disabling write to eFuse %s..." % (efuse.name))
            efuse.disable_write()

        if not self.efuses.burn_all(check_batch_mode=True):
            return
        print("Successful")
