# This file includes the operations with eFuses for ESP32-P4 chip
#
# SPDX-FileCopyrightText: 2023-2025 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: GPL-2.0-or-later

import io
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


class Esp32P4Commands(BaseCommands):
    ################################### CLI definitions ###################################

    def add_cli_commands(self, cli: click.Group):
        super().add_cli_commands(cli)
        blocks_for_keys = EfuseDefineBlocks().get_blocks_for_keys()

        @cli.command(
            "burn-key",
            short_help="Burn a key to a key eFuse block.",
            help="Burn a key to a key eFuse block. Arguments are groups of block name, "
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
            short_help="Burn a digest to a key eFuse block.",
            help="Burn a digest to a key eFuse block. Arguments are groups of block name, "
            "key file (containing 256 bits of binary key data) and key purpose.\n\n"
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
        print("Block version:", self.efuses.get_block_version())
        if self.efuses.get_block_version() >= 1:
            for efuse in self.efuses:
                if efuse.category == "calibration":
                    print(f"{efuse.name:<30} = ", self.efuses[efuse.name].get())

    def _key_block_is_unused(self, block, key_purpose_block):
        if not block.is_readable() or not block.is_writeable():
            return False

        if key_purpose_block.get() != "USER" or not key_purpose_block.is_writeable():
            return False

        if not block.get_bitstring().all(False):
            return False

        return True

    def _get_next_key_block(self, current_key_block, block_name_list):
        key_blocks = [b for b in self.efuses.blocks if b.key_purpose_name]
        start = key_blocks.index(current_key_block)

        # Sort key blocks so that we pick the next free block (and loop around if necessary)
        key_blocks = key_blocks[start:] + key_blocks[0:start]

        # Exclude any other blocks that will be be burned
        key_blocks = [b for b in key_blocks if b.name not in block_name_list]

        for block in key_blocks:
            key_purpose_block = self.efuses[block.key_purpose_name]
            if self._key_block_is_unused(block, key_purpose_block):
                return block

        return None

    def _split_512_bit_key(self, block_name_list, datafile_list, keypurpose_list):
        datafile_list = list(datafile_list)
        block_name_list = list(block_name_list)
        keypurpose_list = list(keypurpose_list)

        i = keypurpose_list.index("XTS_AES_256_KEY")
        block_name = block_name_list[i]

        block_num = self.efuses.get_index_block_by_name(block_name)
        block = self.efuses.blocks[block_num]

        data = datafile_list[i].read()
        if len(data) != 64:
            raise esptool.FatalError(
                "Incorrect key file size %d, XTS_AES_256_KEY should be 64 bytes"
                % len(data)
            )

        key_block_2 = self._get_next_key_block(block, block_name_list)
        if not key_block_2:
            raise esptool.FatalError("XTS_AES_256_KEY requires two free keyblocks")

        keypurpose_list.append("XTS_AES_256_KEY_1")
        datafile_list.append(io.BytesIO(data[:32]))
        block_name_list.append(block_name)

        keypurpose_list.append("XTS_AES_256_KEY_2")
        datafile_list.append(io.BytesIO(data[32:]))
        block_name_list.append(key_block_2.name)

        keypurpose_list.pop(i)
        datafile_list.pop(i)
        block_name_list.pop(i)

        return tuple(block_name_list), tuple(datafile_list), tuple(keypurpose_list)

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

        if "XTS_AES_256_KEY" in keypurpose_list:
            # XTS_AES_256_KEY is not an actual HW key purpose, needs to be split into
            # XTS_AES_256_KEY_1 and XTS_AES_256_KEY_2
            block_name_list, datafile_list, keypurpose_list = self._split_512_bit_key(
                block_name_list, datafile_list, keypurpose_list
            )

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
                if keypurpose == "ECDSA_KEY":
                    sk = espsecure.load_ecdsa_signing_key(datafile)
                    data = espsecure.get_ecdsa_signing_key_raw_bytes(sk)
                    if len(data) == 24:
                        # the private key is 24 bytes long for NIST192p, add 8 bytes of padding
                        data = b"\x00" * 8 + data
                else:
                    data = datafile.read()
                    datafile.close()
            else:
                data = datafile

            print(" - %s" % (efuse.name), end=" ")
            revers_msg = None
            if self.efuses[block.key_purpose_name].need_reverse(keypurpose):
                revers_msg = (
                    f"\tReversing byte order for {keypurpose} hardware peripheral"
                )
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
