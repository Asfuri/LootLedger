using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using LootLedger.ReplayReader;

// Usage: LootLedger.ReplayReader [--trace] <file.replay>...
// Writes one JSON object per replay to stdout, in argument order.
var trace = args.Contains("--trace");
var files = args.Where(a => !a.StartsWith("--", StringComparison.Ordinal)).ToList();
if (files.Count == 0)
{
    Console.Error.WriteLine("Usage: LootLedger.ReplayReader [--trace] <file.replay>...");
    return 2;
}

var options = new JsonSerializerOptions
{
    PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
};
using var output = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { AutoFlush = true };
foreach (var file in files)
{
    output.WriteLine(JsonSerializer.Serialize(ChestReplayReader.Analyze(file, trace), options));
}
return 0;
