#pragma once

// ----------------------------------------------------------------------------
// sha256.hpp - small SHA-256 streaming adapter for deterministic artifacts.
//
// Scope:
//   This header implements FIPS 180-4 SHA-256 for integer-domain artifact
//   digests. It is not a general cryptography abstraction; it exists so the
//   ordering layer can truthfully label `output_hash` as SHA-256 instead of a
//   non-cryptographic mixer.
//
// Design:
//   - Streaming builder: callers update with std::span<const uint8_t>.
//   - Explicit little-endian helpers for repo-local deterministic serialization.
//   - Header-only, no OpenSSL dependency, no dynamic allocation.
//
// Algorithm:
//   - Accumulate input bytes into 512-bit blocks and maintain the byte count
//     so the final length field is \(L = 8n\) bits.
//   - Pad by appending one \(1\) bit, enough \(0\) bits to reach
//     \(448 \pmod{512}\), then the 64-bit big-endian length.
//   - For each block, parse sixteen 32-bit big-endian words and extend them
//     to \(W_0,\ldots,W_{63}\) with the SHA-256 \(\sigma_0,\sigma_1\)
//     schedule functions.
//   - Run 64 compression rounds using \(Ch\), \(Maj\), \(\Sigma_0\),
//     \(\Sigma_1\), and the FIPS round constants, then add the working
//     variables back into the eight-word state.
//   - Emit the final eight state words as a 256-bit big-endian digest.
//
// References:
//   - National Institute of Standards and Technology, Secure Hash Standard
//     (SHS), FIPS PUB 180-4, 2015, DOI: 10.6028/NIST.FIPS.180-4.
// ----------------------------------------------------------------------------

#include <array>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <span>

namespace rch::core {

// Incremental SHA-256 state machine with repo-local byte serialization helpers.
class Sha256 final {
public:
    // Starts with the SHA-256 initial hash values.
    constexpr Sha256() noexcept = default;

    // Absorbs bytes and transforms each complete 512-bit block.
    void update(const std::span<const std::uint8_t> bytes) noexcept {
        if (finalized_) {
            return;
        }
        total_bytes_ += bytes.size();
        for (const std::uint8_t byte : bytes) {
            buffer_[buffer_size_++] = byte;
            if (buffer_size_ == kBlockSize) {
                transform(buffer_);
                buffer_size_ = 0U;
            }
        }
    }

    // Adds one byte to the message stream.
    void update_u8(const std::uint8_t value) noexcept {
        const std::array<std::uint8_t, 1> bytes{value};
        update(bytes);
    }

    // Serializes a 64-bit integer in little-endian order before hashing.
    void update_u64_le(std::uint64_t value) noexcept {
        std::array<std::uint8_t, 8> bytes{};
        for (std::uint8_t& byte : bytes) {
            byte = static_cast<std::uint8_t>(value & 0xFFU);
            value >>= 8U;
        }
        update(bytes);
    }

    // Applies FIPS padding and returns the 256-bit digest. Finalization is
    // idempotent; updates after finalization are ignored.
    [[nodiscard]] auto finalize() noexcept -> std::array<std::uint8_t, 32> {
        if (finalized_) {
            return digest_;
        }

        const std::uint64_t bit_count = static_cast<std::uint64_t>(total_bytes_) * 8ULL;

        update_u8(0x80U);
        while (buffer_size_ != 56U) {
            if (buffer_size_ == kBlockSize) {
                transform(buffer_);
                buffer_size_ = 0U;
            }
            update_u8(0U);
        }

        std::array<std::uint8_t, 8> length_bytes{};
        std::uint64_t length = bit_count;
        for (std::size_t i = 0U; i < length_bytes.size(); ++i) {
            length_bytes[length_bytes.size() - 1U - i] = static_cast<std::uint8_t>(length & 0xFFU);
            length >>= 8U;
        }
        update(length_bytes);

        std::array<std::uint8_t, 32> digest{};
        for (std::size_t word = 0U; word < state_.size(); ++word) {
            digest[(4U * word) + 0U] = static_cast<std::uint8_t>((state_[word] >> 24U) & 0xFFU);
            digest[(4U * word) + 1U] = static_cast<std::uint8_t>((state_[word] >> 16U) & 0xFFU);
            digest[(4U * word) + 2U] = static_cast<std::uint8_t>((state_[word] >> 8U) & 0xFFU);
            digest[(4U * word) + 3U] = static_cast<std::uint8_t>(state_[word] & 0xFFU);
        }
        digest_ = digest;
        finalized_ = true;
        return digest_;
    }

private:
    // SHA-256 processes 512-bit message blocks.
    static constexpr std::size_t kBlockSize = 64U;
    // FIPS 180-4 section 4.2.2 round constants.
    static constexpr std::array<std::uint32_t, 64> kRoundConstants{
        0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U, 0x3956c25bU, 0x59f111f1U, 0x923f82a4U,
        0xab1c5ed5U, 0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U, 0x72be5d74U, 0x80deb1feU,
        0x9bdc06a7U, 0xc19bf174U, 0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU, 0x2de92c6fU,
        0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU, 0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U,
        0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U, 0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU,
        0x53380d13U, 0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U, 0xa2bfe8a1U, 0xa81a664bU,
        0xc24b8b70U, 0xc76c51a3U, 0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U, 0x19a4c116U,
        0x1e376c08U, 0x2748774cU, 0x34b0bcb5U, 0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
        0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U, 0x90befffaU, 0xa4506cebU, 0xbef9a3f7U,
        0xc67178f2U,
    };

    std::array<std::uint32_t, 8> state_{
        0x6a09e667U,
        0xbb67ae85U,
        0x3c6ef372U,
        0xa54ff53aU,
        0x510e527fU,
        0x9b05688cU,
        0x1f83d9abU,
        0x5be0cd19U,
    };
    std::array<std::uint8_t, kBlockSize> buffer_{};
    std::array<std::uint8_t, 32> digest_{};
    std::size_t buffer_size_{};
    std::size_t total_bytes_{};
    bool finalized_{};

    // FIPS Ch function: selects bits from y or z according to x.
    [[nodiscard]] static constexpr auto
    choose(const std::uint32_t x, const std::uint32_t y, const std::uint32_t z) noexcept
        -> std::uint32_t {
        return (x & y) ^ (~x & z);
    }

    // FIPS Maj function: returns the per-bit majority of x, y, and z.
    [[nodiscard]] static constexpr auto
    majority(const std::uint32_t x, const std::uint32_t y, const std::uint32_t z) noexcept
        -> std::uint32_t {
        return (x & y) ^ (x & z) ^ (y & z);
    }

    // FIPS upper-case Sigma0 rotation mix.
    [[nodiscard]] static constexpr auto big_sigma0(const std::uint32_t value) noexcept
        -> std::uint32_t {
        return std::rotr(value, 2) ^ std::rotr(value, 13) ^ std::rotr(value, 22);
    }

    // FIPS upper-case Sigma1 rotation mix.
    [[nodiscard]] static constexpr auto big_sigma1(const std::uint32_t value) noexcept
        -> std::uint32_t {
        return std::rotr(value, 6) ^ std::rotr(value, 11) ^ std::rotr(value, 25);
    }

    // FIPS lower-case sigma0 schedule mix.
    [[nodiscard]] static constexpr auto small_sigma0(const std::uint32_t value) noexcept
        -> std::uint32_t {
        return std::rotr(value, 7) ^ std::rotr(value, 18) ^ (value >> 3U);
    }

    // FIPS lower-case sigma1 schedule mix.
    [[nodiscard]] static constexpr auto small_sigma1(const std::uint32_t value) noexcept
        -> std::uint32_t {
        return std::rotr(value, 17) ^ std::rotr(value, 19) ^ (value >> 10U);
    }

    // Runs the SHA-256 compression function on one 512-bit block.
    void transform(const std::array<std::uint8_t, kBlockSize>& block) noexcept {
        std::array<std::uint32_t, 64> words{};
        for (std::size_t i = 0U; i < 16U; ++i) {
            words[i] = (static_cast<std::uint32_t>(block[(4U * i) + 0U]) << 24U) |
                       (static_cast<std::uint32_t>(block[(4U * i) + 1U]) << 16U) |
                       (static_cast<std::uint32_t>(block[(4U * i) + 2U]) << 8U) |
                       static_cast<std::uint32_t>(block[(4U * i) + 3U]);
        }
        for (std::size_t i = 16U; i < words.size(); ++i) {
            words[i] = small_sigma1(words[i - 2U]) + words[i - 7U] + small_sigma0(words[i - 15U]) +
                       words[i - 16U];
        }

        auto a = state_[0];
        auto b = state_[1];
        auto c = state_[2];
        auto d = state_[3];
        auto e = state_[4];
        auto f = state_[5];
        auto g = state_[6];
        auto h = state_[7];

        for (std::size_t i = 0U; i < words.size(); ++i) {
            const std::uint32_t t1 =
                h + big_sigma1(e) + choose(e, f, g) + kRoundConstants[i] + words[i];
            const std::uint32_t t2 = big_sigma0(a) + majority(a, b, c);
            h = g;
            g = f;
            f = e;
            e = d + t1;
            d = c;
            c = b;
            b = a;
            a = t1 + t2;
        }

        state_[0] += a;
        state_[1] += b;
        state_[2] += c;
        state_[3] += d;
        state_[4] += e;
        state_[5] += f;
        state_[6] += g;
        state_[7] += h;
    }
};

[[nodiscard]] inline auto sha256_bytes(const std::span<const std::uint8_t> bytes) noexcept
    -> std::array<std::uint8_t, 32> {
    Sha256 sha{};
    sha.update(bytes);
    return sha.finalize();
}

} // namespace rch::core
