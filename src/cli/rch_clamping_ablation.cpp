// Controlled saturation experiment. This CLI does not alter the RCH algorithm.
#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

#include "rch/orderings/orderer.hpp"

namespace {
using Point = rch::core::Vec3<double>;
using Signed = std::array<std::int64_t, 3>;
struct Cloud {
    std::vector<double> xyz;
    rch::orderings::OrderingResult fit;
    std::vector<Point> projected;
    std::vector<Signed> unclipped, clamped;
    std::size_t clipped{};
};
Cloud load(const std::filesystem::path& path) {
    Cloud cloud;
    std::ifstream stream(path);
    if (!stream)
        throw std::runtime_error("cannot open points");
    std::string line;
    while (std::getline(stream, line)) {
        std::replace(line.begin(), line.end(), ',', ' ');
        std::istringstream row(line);
        double x{}, y{}, z{};
        std::string extra;
        if (!(row >> x >> y >> z) || (row >> extra))
            throw std::runtime_error("invalid point row");
        for (double value : {x, y, z}) {
            if (!std::isfinite(value))
                throw std::runtime_error("non-finite input");
            cloud.xyz.push_back(value == 0.0 ? 0.0 : value);
        }
    }
    auto fit = rch::orderings::order_point_cloud(cloud.xyz);
    if (!fit || cloud.xyz.empty())
        throw std::runtime_error("native C3 fit failed/empty");
    cloud.fit = std::move(*fit);
    rch::frames::RobustPrincipalFrame frame;
    frame.axes = cloud.fit.frame_axes;
    for (std::size_t i = 0; i < cloud.xyz.size() / 3; ++i) {
        const Point raw{cloud.xyz[3 * i], cloud.xyz[3 * i + 1], cloud.xyz[3 * i + 2]};
        auto projected = rch::frames::project_to_robust_frame(raw, cloud.fit.center, frame);
        Signed unclipped{}, clamped{};
        bool outside = false;
        for (std::size_t j = 0; j < 3; ++j) {
            const auto half = cloud.fit.half_extent[j];
            if (!(half > 0) || !std::isfinite(half))
                throw std::runtime_error("invalid native domain: no intervention defined");
            const double value = projected[j];
            const auto bits = cloud.fit.bits_axis[j];
            const auto native = rch::curves::quantize_axis(value, -half, half, bits);
            clamped[j] = static_cast<std::int64_t>(native);
            // Retain native CLOSED upper-bound semantics for all in-domain points.
            unclipped[j] = clamped[j];
            if (value < -half || value > half) {
                outside = true;
                const long double q = std::floor(
                    (static_cast<long double>(value) + static_cast<long double>(half)) /
                    (2.0L * static_cast<long double>(half)) *
                    std::ldexp(1.0L, static_cast<int>(bits))
                );
                if (!std::isfinite(q) || std::abs(q) >= static_cast<long double>(INT64_MAX / 4))
                    throw std::runtime_error("signed lattice overflow");
                unclipped[j] = static_cast<std::int64_t>(q);
            }
        }
        cloud.clipped += static_cast<std::size_t>(outside);
        cloud.projected.push_back(projected);
        cloud.unclipped.push_back(unclipped);
        cloud.clamped.push_back(clamped);
        rch::curves::Point3u32 q{
            static_cast<std::uint32_t>(clamped[0]),
            static_cast<std::uint32_t>(clamped[1]),
            static_cast<std::uint32_t>(clamped[2])
        };
        if (rch::curves::Hilbert3Compact::encode(q, cloud.fit.bits_axis) !=
            cloud.fit.primary_keys[i])
            throw std::runtime_error("native quantizer/key replay mismatch");
    }
    if (cloud.clipped != cloud.fit.quantization_diagnostics.domain_clipped_point_count)
        throw std::runtime_error("native clipping diagnostic mismatch");
    return cloud;
}
std::vector<std::uint64_t>
sorted(const Cloud& c, const std::vector<std::uint64_t>& keys, bool projected_tie) {
    std::vector<std::uint64_t> ids(keys.size());
    std::iota(ids.begin(), ids.end(), 0);
    std::ranges::sort(ids, [&](auto a, auto b) {
        if (keys[a] != keys[b])
            return keys[a] < keys[b];
        if (projected_tie)
            for (std::size_t j = 0; j < 3; ++j) {
                const auto x = rch::core::double_total_order_key(c.projected[a][j]);
                const auto y = rch::core::double_total_order_key(c.projected[b][j]);
                if (x != y)
                    return x < y;
            }
        for (std::size_t j = 0; j < 3; ++j) {
            const auto x = rch::core::double_total_order_key(c.xyz[3 * a + j]);
            const auto y = rch::core::double_total_order_key(c.xyz[3 * b + j]);
            if (x != y)
                return x < y;
        }
        return a < b;
    });
    return ids;
}
std::size_t shared(std::vector<std::uint64_t> keys) {
    std::ranges::sort(keys);
    std::size_t result = 0;
    for (std::size_t begin = 0; begin < keys.size();) {
        std::size_t end = begin + 1;
        while (end < keys.size() && keys[end] == keys[begin])
            ++end;
        if (end - begin > 1)
            result += end - begin;
        begin = end;
    }
    return result;
}
void write_order(
    const std::filesystem::path& path,
    const std::vector<std::uint64_t>& ids,
    const std::vector<std::uint64_t>& keys
) {
    std::ofstream f(path);
    f << "rank,raw_index,key\n";
    for (std::size_t rank = 0; rank < ids.size(); ++rank)
        f << rank << ',' << ids[rank] << ',' << keys[ids[rank]] << '\n';
    if (!f)
        throw std::runtime_error("failed writing order");
}
void run(const std::filesystem::path& output, const std::vector<std::filesystem::path>& inputs) {
    if (inputs.empty() || std::filesystem::exists(output))
        throw std::runtime_error("inputs required; output must not exist");
    std::vector<Cloud> clouds;
    for (const auto& path : inputs)
        clouds.push_back(load(path));
    const auto clean_count = clouds.front().xyz.size() / 3;
    for (const auto& cloud : clouds)
        if (cloud.xyz.size() < clouds.front().xyz.size() ||
            !std::equal(clouds.front().xyz.begin(), clouds.front().xyz.end(), cloud.xyz.begin()))
            throw std::runtime_error("original inlier IDs were not retained as prefix");
    Signed lo{}, hi{}, offset{};
    rch::curves::BitsAxis3 extended{};
    for (const auto& cloud : clouds)
        for (std::size_t j = 0; j < 3; ++j) {
            hi[j] = std::max(
                hi[j],
                static_cast<std::int64_t>(
                    rch::curves::quantization_max_code(cloud.fit.bits_axis[j])
                )
            );
            for (const auto& q : cloud.unclipped) {
                lo[j] = std::min(lo[j], q[j]);
                hi[j] = std::max(hi[j], q[j]);
            }
        }
    for (std::size_t j = 0; j < 3; ++j) {
        offset[j] = -lo[j];
        const auto extent = static_cast<std::uint64_t>(hi[j] + offset[j]);
        const auto bits = std::max(1, static_cast<int>(std::bit_width(extent)));
        if (bits > 32)
            throw std::runtime_error("extended axis exceeds uint32 budget");
        extended[j] = static_cast<std::uint8_t>(bits);
    }
    if (!rch::curves::Hilbert3Compact::valid_bits(extended))
        throw std::runtime_error("extended total exceeds 63 bits");
    std::filesystem::create_directories(output);
    std::ofstream protocol(output / "embedding.json");
    protocol << "{\"clean_point_count\":" << clean_count << ",\"extended_bits\":["
             << int(extended[0]) << ',' << int(extended[1]) << ',' << int(extended[2])
             << "],\"offset\":[" << offset[0] << ',' << offset[1] << ',' << offset[2] << "]}\n";
    std::ofstream diagnostics(output / "diagnostics.csv");
    diagnostics << "condition,arm,point_count,clipped_point_count,shared_key_point_count,native_"
                   "robust_fallback\n";
    for (std::size_t d = 0; d < clouds.size(); ++d) {
        const auto& c = clouds[d];
        std::ofstream grid(output / ("D" + std::to_string(d) + ".grid.csv"));
        grid << "raw_index,x,y,z,projected_x,projected_y,projected_z,q0,q1,q2,unclipped0,"
                "unclipped1,unclipped2\n"
             << std::setprecision(17);
        for (std::size_t i = 0; i < c.projected.size(); ++i) {
            grid << i;
            for (std::size_t j = 0; j < 3; ++j)
                grid << ',' << c.xyz[3 * i + j];
            for (auto value : c.projected[i])
                grid << ',' << value;
            for (auto value : c.clamped[i])
                grid << ',' << value;
            for (auto value : c.unclipped[i])
                grid << ',' << value;
            grid << '\n';
        }
        std::ofstream frame(output / ("D" + std::to_string(d) + ".frame.csv"));
        frame << "axis,center,half_extent,native_bits,cell_width,axis0,axis1,axis2\n"
              << std::setprecision(17);
        for (std::size_t j = 0; j < 3; ++j)
            frame << j << ',' << c.fit.center[j] << ',' << c.fit.half_extent[j] << ','
                  << int(c.fit.bits_axis[j]) << ','
                  << std::ldexp(2 * c.fit.half_extent[j], -int(c.fit.bits_axis[j])) << ','
                  << c.fit.frame_axes(0, j) << ',' << c.fit.frame_axes(1, j) << ','
                  << c.fit.frame_axes(2, j) << '\n';
        for (const std::string arm : {"native", "tie_projected", "clamp_on", "clamp_off"}) {
            auto keys = c.fit.primary_keys;
            if (arm == "clamp_on" || arm == "clamp_off") {
                const auto& tuples = arm == "clamp_on" ? c.clamped : c.unclipped;
                for (std::size_t i = 0; i < tuples.size(); ++i) {
                    rch::curves::Point3u32 point{};
                    for (std::size_t j = 0; j < 3; ++j)
                        point[j] = static_cast<std::uint32_t>(tuples[i][j] + offset[j]);
                    const auto key = rch::curves::Hilbert3Compact::encode(point, extended);
                    if (!key || rch::curves::Hilbert3Compact::decode(*key, extended) != point)
                        throw std::runtime_error("extended encode/decode mismatch");
                    keys[i] = *key;
                }
            }
            const auto ids = sorted(c, keys, arm == "tie_projected");
            if (arm == "native" && ids != c.fit.permutation)
                throw std::runtime_error("native tie/permutation replay mismatch");
            write_order(output / ("D" + std::to_string(d) + "." + arm + ".order.csv"), ids, keys);
            diagnostics << 'D' << d << ',' << arm << ',' << keys.size() << ',' << c.clipped << ','
                        << shared(keys) << ',' << c.fit.robust_fallback_used << '\n';
        }
    }
}
} // namespace
int main(int argc, char** argv) {
    try {
        std::filesystem::path output;
        std::vector<std::filesystem::path> inputs;
        for (int i = 1; i < argc; i += 2) {
            if (i + 1 >= argc)
                throw std::runtime_error(
                    "expected --output DIR and repeated --input CSV, clean first"
                );
            const std::string flag = argv[i];
            if (flag == "--output")
                output = argv[i + 1];
            else if (flag == "--input")
                inputs.emplace_back(argv[i + 1]);
            else
                throw std::runtime_error("unknown argument");
        }
        if (output.empty())
            throw std::runtime_error("--output is required");
        run(output, inputs);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
