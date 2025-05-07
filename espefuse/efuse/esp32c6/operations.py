# This file includes the operations with eFuses for ESP32-C6 chip
#
# SPDX-FileCopyrightText: 2022-2025 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: GPL-2.0-or-later

import rich_click as click

import espsecure
import esptool

from . import fields
from .mem_definition import EfuseDefineBlocks
from .. import util
from ..base_operations import (
    BaseCommands,
    NonCompositeTuple,
    TupleParameter,
    add_force_write_always,
    add_show_sensitive_info_option,
    protect_options,
)


class Esp32C6Commands(BaseCommands):
    ################################### CLI definitions ###################################

    def add_cli_commands(self, cli: click.Group):
        super().add_cli_commands(cli)
        blocks_for_keys = EfuseDefineBlocks().get_blocks_for_keys()

        @cli.command(
            "burn-key",
            help="Burn the key block with the specified name. Arguments are groups of block name, "
            "key file (containing 256 bits of binary key data) and key purpose.\n\n"
            f"Block is one of: [{', '.join(blocks_for_keys)}]\n\n"
            f"Key purpose is one of: [{', '.join(fields.EfuseKeyPurposeField.KEY_PURPOSES_NAME)}]",
        )
        @click.argument(
            "block_keyfile_keypurpose",
            metavar="<BLOCK> <KEYFILE> <KEYPURPOSE>",
            cls=TupleParameter,
            required=True,
            nargs=-1,
            max_arity=len(blocks_for_keys),
            type=NonCompositeTuple(
                [
                    click.Choice(blocks_for_keys),
                    click.File("rb"),
                    click.Choice(fields.EfuseKeyPurposeField.KEY_PURPOSES_NAME),
                ]
            ),
        )
        @protect_options
        @add_force_write_always
        @add_show_sensitive_info_option
        def burn_key_cli(**kwargs):
            kwargs.pop("force_write_always")
            block, keyfile, keypurpose = zip(*kwargs.pop("block_keyfile_keypurpose"))
            self.burn_key(block, keyfile, keypurpose, **kwargs)

        @cli.command(
            "burn-key-digest",
            short_help="Parse a RSA public key and burn the digest.",
            help="Parse a RSA public key and burn the digest to key eFuse block.\n\n"
            f"Block is one of: [{', '.join(blocks_for_keys)}]\n\n"
            f"Key purpose is one of: [{', '.join(fields.EfuseKeyPurposeField.DIGEST_KEY_PURPOSES)}]",
        )
        @click.argument(
            "block_keyfile_keypurpose",
            metavar="<BLOCK> <KEYFILE> <KEYPURPOSE>",
            cls=TupleParameter,
            required=True,
            nargs=-1,
            max_arity=len(blocks_for_keys),
            type=NonCompositeTuple(
                [
                    click.Choice(blocks_for_keys),
                    click.File("rb"),
                    click.Choice(fields.EfuseKeyPurposeField.DIGEST_KEY_PURPOSES),
                ]
            ),
        )
        @protect_options
        @add_force_write_always
        @add_show_sensitive_info_option
        def burn_key_digest_cli(**kwargs):
            kwargs.pop("force_write_always")
            block, keyfile, keypurpose = zip(*kwargs.pop("block_keyfile_keypurpose"))
            self.burn_key_digest(block, keyfile, keypurpose, **kwargs)

    ###################################### Commands ######################################

    def adc_info(self):
        # fmt: off
        print("Block version:", self.efuses.get_block_version())
        if self.efuses.get_block_version() >= 1:
            print("Temperature Sensor Calibration = {}C".format(self.efuses["TEMP_CALIB"].get()))
            print("ADC OCode             = ", self.efuses["OCODE"].get())
            print("ADC1:")
            print("INIT_CODE_ATTEN0     = ", self.efuses['ADC1_INIT_CODE_ATTEN0'].get())
            print("INIT_CODE_ATTEN1     = ", self.efuses['ADC1_INIT_CODE_ATTEN1'].get())
            print("INIT_CODE_ATTEN2     = ", self.efuses['ADC1_INIT_CODE_ATTEN2'].get())
            print("INIT_CODE_ATTEN3     = ", self.efuses['ADC1_INIT_CODE_ATTEN3'].get())
            print("CAL_VOL_ATTEN0       = ", self.efuses['ADC1_CAL_VOL_ATTEN0'].get())
            print("CAL_VOL_ATTEN1       = ", self.efuses['ADC1_CAL_VOL_ATTEN1'].get())
            print("CAL_VOL_ATTEN2       = ", self.efuses['ADC1_CAL_VOL_ATTEN2'].get())
            print("CAL_VOL_ATTEN3       = ", self.efuses['ADC1_CAL_VOL_ATTEN3'].get())
            print("INIT_CODE_ATTEN0_CH0 = ", self.efuses['ADC1_INIT_CODE_ATTEN0_CH0'].get())
            print("INIT_CODE_ATTEN0_CH1 = ", self.efuses['ADC1_INIT_CODE_ATTEN0_CH1'].get())
            print("INIT_CODE_ATTEN0_CH2 = ", self.efuses['ADC1_INIT_CODE_ATTEN0_CH2'].get())
            print("INIT_CODE_ATTEN0_CH3 = ", self.efuses['ADC1_INIT_CODE_ATTEN0_CH3'].get())
            print("INIT_CODE_ATTEN0_CH4 = ", self.efuses['ADC1_INIT_CODE_ATTEN0_CH4'].get())
            print("INIT_CODE_ATTEN0_CH5 = ", self.efuses['ADC1_INIT_CODE_ATTEN0_CH5'].get())
            print("INIT_CODE_ATTEN0_CH6 = ", self.efuses['ADC1_INIT_CODE_ATTEN0_CH6'].get())
        # fmt: on

    def burn_key(
        self,
        block,
        keyfile,
        keypurpose,
        no_write_protect,
        no_read_protect,
        show_sensitive_info,
        digest=None,
    ):
        if digest is None:
            datafile_list = keyfile[
                0 : len([name for name in keyfile if name is not None]) :
            ]
        else:
            datafile_list = digest[
                0 : len([name for name in digest if name is not None]) :
            ]
        block_name_list = block[0 : len([name for name in block if name is not None]) :]
        keypurpose_list = keypurpose[
            0 : len([name for name in keypurpose if name is not None]) :
        ]

        util.check_duplicate_name_in_list(block_name_list)
        if len(block_name_list) != len(datafile_list) or len(block_name_list) != len(
            keypurpose_list
        ):
            raise esptool.FatalError(
                "The number of blocks (%d), datafile (%d) and keypurpose (%d) should be the same."
                % (len(block_name_list), len(datafile_list), len(keypurpose_list))
            )

        print("Burn keys to blocks:")
        for block_name, datafile, keypurpose in zip(
            block_name_list, datafile_list, keypurpose_list
        ):
            efuse = None
            for block in self.efuses.blocks:
                if block_name == block.name or block_name in block.alias:
                    efuse = self.efuses[block.name]
            if efuse is None:
                raise esptool.FatalError("Unknown block name - %s" % (block_name))
            num_bytes = efuse.bit_len // 8

            block_num = self.efuses.get_index_block_by_name(block_name)
            block = self.efuses.blocks[block_num]

            if digest is None:
                data = datafile.read()
                datafile.close()
            else:
                data = datafile

            print(" - %s" % (efuse.name), end=" ")
            revers_msg = None
            if self.efuses[block.key_purpose_name].need_reverse(keypurpose):
                revers_msg = "\tReversing byte order for AES-XTS hardware peripheral"
                data = data[::-1]
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
                    "Incorrect key file size %d. Key file must be %d bytes (%d bits) "
                    "of raw binary key data." % (len(data), num_bytes, num_bytes * 8)
                )

            if self.efuses[block.key_purpose_name].need_rd_protect(keypurpose):
                read_protect = False if no_read_protect else True
            else:
                read_protect = False
            write_protect = not no_write_protect

            # using eFuse instead of a block gives the advantage of checking it as the whole field.
            efuse.save(data)

            disable_wr_protect_key_purpose = False
            if self.efuses[block.key_purpose_name].get() != keypurpose:
                if self.efuses[block.key_purpose_name].is_writeable():
                    print(
                        "\t'%s': '%s' -> '%s'."
                        % (
                            block.key_purpose_name,
                            self.efuses[block.key_purpose_name].get(),
                            keypurpose,
                        )
                    )
                    self.efuses[block.key_purpose_name].save(keypurpose)
                    disable_wr_protect_key_purpose = True
                else:
                    raise esptool.FatalError(
                        "It is not possible to change '%s' to '%s' "
                        "because write protection bit is set."
                        % (block.key_purpose_name, keypurpose)
                    )
            else:
                print("\t'%s' is already '%s'." % (block.key_purpose_name, keypurpose))
                if self.efuses[block.key_purpose_name].is_writeable():
                    disable_wr_protect_key_purpose = True

            if disable_wr_protect_key_purpose:
                print("\tDisabling write to '%s'." % block.key_purpose_name)
                self.efuses[block.key_purpose_name].disable_write()

            if read_protect:
                print("\tDisabling read to key block")
                efuse.disable_read()

            if write_protect:
                print("\tDisabling write to key block")
                efuse.disable_write()
            print("")

        if not write_protect:
            print("Keys will remain writeable (due to --no-write-protect)")
        if no_read_protect:
            print("Keys will remain readable (due to --no-read-protect)")

        if not self.efuses.burn_all(check_batch_mode=True):
            return
        print("Successful")

    def burn_key_digest(
        self,
        block,
        keyfile,
        keypurpose,
        no_write_protect,
        no_read_protect,
        show_sensitive_info,
    ):
        digest_list = []
        datafile_list = keyfile[
            0 : len([name for name in keyfile if name is not None]) :
        ]
        block_list = block[0 : len([block for block in block if block is not None]) :]

        for block_name, datafile in zip(block_list, datafile_list):
            efuse = None
            for block in self.efuses.blocks:
                if block_name == block.name or block_name in block.alias:
                    efuse = self.efuses[block.name]
            if efuse is None:
                raise esptool.FatalError("Unknown block name - %s" % (block_name))
            num_bytes = efuse.bit_len // 8
            digest = espsecure._digest_sbv2_public_key(datafile)
            if len(digest) != num_bytes:
                raise esptool.FatalError(
                    "Incorrect digest size %d. Digest must be %d bytes (%d bits) "
                    "of raw binary key data." % (len(digest), num_bytes, num_bytes * 8)
                )
            digest_list.append(digest)

        self.burn_key(
            block_list,
            datafile_list,
            keypurpose,
            no_write_protect,
            no_read_protect,
            show_sensitive_info,
            digest=digest_list,
        )
