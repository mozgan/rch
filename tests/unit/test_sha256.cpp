#include <algorithm>
#include <array>
#include <cstdint>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include "rch/core/sha256.hpp"
#include "rch/orderings/orderer.hpp"

#include <gtest/gtest.h>

namespace {

[[nodiscard]] auto digest_hex(const std::span<const std::uint8_t> bytes) -> std::string {
    const auto digest = rch::core::sha256_bytes(bytes);
    const auto hex = rch::orderings::hash_hex(digest);
    return std::string{hex.data()};
}

[[nodiscard]] auto bytes_from_string(const std::string_view text) -> std::span<const std::uint8_t> {
    return {
        reinterpret_cast<const std::uint8_t*>(text.data()),
        text.size(),
    };
}

TEST(Sha256, MatchesNistEmptyMessageVector) {
    constexpr std::array<std::uint8_t, 0> empty{};
    EXPECT_EQ(
        digest_hex(empty), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    );
}

TEST(Sha256, MatchesNistAbcVector) {
    EXPECT_EQ(
        digest_hex(bytes_from_string("abc")),
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    );
}

TEST(Sha256, MatchesNistMillionAStressVector) {
    const std::vector<std::uint8_t> input(1'000'000U, static_cast<std::uint8_t>('a'));
    EXPECT_EQ(
        digest_hex(std::span<const std::uint8_t>{input}),
        "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0"
    );
}

TEST(Sha256, HashesAllByteValues) {
    std::vector<std::uint8_t> input(256U);
    for (std::size_t i = 0U; i < input.size(); ++i) {
        input[i] = static_cast<std::uint8_t>(i);
    }

    EXPECT_EQ(
        digest_hex(std::span<const std::uint8_t>{input}),
        "40aff2e9d2d8922e47afd4648e6967497158785fbd1da870e7110266bf944880"
    );
}

TEST(Sha256, StreamingAndOneShotAgree) {
    rch::core::Sha256 streaming{};
    streaming.update(bytes_from_string("a"));
    streaming.update(bytes_from_string("bc"));

    EXPECT_EQ(streaming.finalize(), rch::core::sha256_bytes(bytes_from_string("abc")));
}

TEST(Sha256, RespectsFipsPaddingRuleAcrossBlockBoundaries) {
    struct Case {
        std::size_t length;
        std::string_view expected;
    };
    constexpr std::array<Case, 6> cases{{
        {55U, "8963cc0afd622cc7574ac2011f93a3059b3d65548a77542a1559e3d202e6ab00"},
        {56U, "6ea719cefa4b31862035a7fa606b7cc3602f46231117d135cc7119b3c1412314"},
        {63U, "1b58d00f5b1fbd2a1884d666a2be33c2fa7463dff32cd60ef200c0f750a6b70f"},
        {64U, "d53eda7a637c99cc7fb566d96e9fa109bf15c478410a3f5eb4d4c4e26cd081f6"},
        {119U, "17d2f0f7197a6612e311d141781f2b9539c4aef7affd729246c401890e000dde"},
        {120U, "a4f4256159ea6fb23b27eb8c5eb9cfb9083475985f355a85c78de8f2fef2b3ac"},
    }};
    for (const auto& c : cases) {
        const std::vector<std::uint8_t> input(c.length, static_cast<std::uint8_t>('A'));
        EXPECT_EQ(digest_hex(std::span<const std::uint8_t>{input}), c.expected)
            << "length=" << c.length;
    }
}

TEST(Sha256, UpdateU64LeMatchesExplicitByteStreamSerialization) {
    constexpr std::uint64_t value = UINT64_C(0x0123456789ABCDEF);
    rch::core::Sha256 via_u64{};
    via_u64.update_u64_le(value);
    const auto digest_u64 = via_u64.finalize();

    constexpr std::array<std::uint8_t, 8> little_endian{
        0xEFU,
        0xCDU,
        0xABU,
        0x89U,
        0x67U,
        0x45U,
        0x23U,
        0x01U,
    };
    rch::core::Sha256 via_bytes{};
    via_bytes.update(std::span<const std::uint8_t>{little_endian});
    const auto digest_bytes = via_bytes.finalize();

    EXPECT_EQ(digest_u64, digest_bytes);
}

TEST(Sha256, ArbitraryChunkingProducesIdenticalDigest) {
    std::vector<std::uint8_t> input(200U);
    for (std::size_t i = 0U; i < input.size(); ++i) {
        input[i] = static_cast<std::uint8_t>((i * 31U + 7U) & 0xFFU);
    }
    const auto reference = rch::core::sha256_bytes(std::span<const std::uint8_t>{input});

    rch::core::Sha256 chunked{};
    constexpr std::array<std::size_t, 6> sizes{1U, 7U, 64U, 65U, 33U, 30U};
    std::size_t cursor = 0U;
    for (const auto size : sizes) {
        const auto take = std::min(size, input.size() - cursor);
        if (take == 0U) {
            break;
        }
        chunked.update(std::span<const std::uint8_t>{input.data() + cursor, take});
        cursor += take;
    }
    // Drain any tail with one final span so cursor reaches input.size().
    if (cursor < input.size()) {
        chunked.update(std::span<const std::uint8_t>{input.data() + cursor, input.size() - cursor});
    }
    EXPECT_EQ(chunked.finalize(), reference);
}

TEST(Sha256, EverySmallChunkSizeProducesIdenticalDigest) {
    std::vector<std::uint8_t> input(257U);
    for (std::size_t i = 0U; i < input.size(); ++i) {
        input[i] = static_cast<std::uint8_t>((i * 17U + 91U) & 0xFFU);
    }
    const auto reference = rch::core::sha256_bytes(std::span<const std::uint8_t>{input});

    for (std::size_t chunk_size = 1U; chunk_size <= 65U; ++chunk_size) {
        rch::core::Sha256 chunked{};
        chunked.update(std::span<const std::uint8_t>{});

        for (std::size_t cursor = 0U; cursor < input.size(); cursor += chunk_size) {
            const auto take = std::min(chunk_size, input.size() - cursor);
            chunked.update(std::span<const std::uint8_t>{input.data() + cursor, take});
        }

        EXPECT_EQ(chunked.finalize(), reference) << "chunk_size=" << chunk_size;
    }
}

TEST(Sha256, FinalizeIsIdempotentAndConsumesStream) {
    rch::core::Sha256 sha{};
    sha.update(bytes_from_string("abc"));

    const auto first = sha.finalize();
    EXPECT_EQ(sha.finalize(), first);

    sha.update(bytes_from_string("def"));
    sha.update_u8(0U);
    sha.update_u64_le(42U);
    EXPECT_EQ(sha.finalize(), first);
}

} // namespace
