 The .mzp format (Incomplete)
=================
> Revision 0, maintainer: Waku_Waku

> Reverse-engineered by Waku_Waku

All fields are little-endian unless specified otherwise.


 Introduction
==============

The .mzp archive format is mostly used in consumer titles in Playstation 2-era and early PSP lifetime, in a limited production subset from Interchannel and Piacci, such as "Kyuuketsu Kitan Moon Ties", "Like Life Every Hour" or even PS3 title "Suzukaze no Melt Days in the Sanctuary".


It is not to be confused with the top-level MRG/HED/NAM structure, or with F&C's MRG format.

 I) .mzp structure (header: 0x6 bytes)
=======================================
	6 bytes - 'mrgd00' signature (0x6D 0x72 0x67 0x64 0x30 0x30)
	2 bytes - number of archive entry descriptors
	{ n times (0x8 bytes): Archive Entry Descriptor }
	{ Data }


 I.1)  Archive Entry Descriptor
--------------------------------

	2 bytes - offset, sector count (0x800 bytes)
	2 bytes - offset, within sector
	2 bytes - size upper boundary, sector count (0x800 bytes)
	2 bytes - size in data section (Raw)

Location of entry data within the archive is calculated as such:

- data start offset is (header size) = (6 + 2 + n * 8) bytes [see section I]
- Real offset = data start offset + .ofsSect * 0x800 + .ofsByte
- .upperBoundSectCount * 0x800 <= .sizeRaw so an entry is at most 0x10000 bytes


 II) First Entry (picture / animation)
=======================================

The first entry is stored with no MZX compression and is not a mrgd00 header. It contains info about the image.

Example:
	E0 01 10 01 40 00 80 00 08 00 03 00 01 00 01 00

	2 bytes - width (1E0 = 480)
	2 bytes - height (110 = 272)
	2 bytes - tileWidth (40 = 64) 8 tiles large (8 * 64 = 512)
	2 bytes - tileHeight (80 = 128) 3 tiles high (3 * 128 = 384)
	2 bytes - tileXCount
	2 bytes - tileYCount
	2 bytes - bitmap characteristics (palettized, etc.)
	2 bytes - unknown?
	{ if unknown? == 0x01: (256 * 4 bytes): color palette }

beware, palette data is ABGR (RR GG BB AA in little-endian)

-to be edited-

