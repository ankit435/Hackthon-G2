# English query set: human verification sheet

For each query, check that (1) the query is sensible for its kind, keyword = exact term
from the audio and semantic = paraphrase or concept, and (2) **every** listed evidence segment
answers it and **no obviously relevant segment is missing**. Mark problems inline and tell
the agent. When all are OK, set `verified: true` and `verified_by` in `en.json`.

Totals: 45 keyword, 45 semantic.

## audio_01_rate_limiter__k1 [keyword] Lua script
_origin: drafted_
- `audio_01_rate_limiter#21` SPEAKER_01 168.8s: We should do the whole check and decrement inside a single Lua script so the read, the compare and the write are atomic on the Redis side.
- `audio_01_rate_limiter#54` SPEAKER_00 424.2s: So to summarize, token bucket in Redis with atomic Lua scripts, local leases for hot keys, explicit fail open policy, and standard headers.

## audio_01_rate_limiter__k2 [keyword] corporate NAT
_origin: drafted_
- `audio_01_rate_limiter#4` SPEAKER_00 30.3s: That makes sense. IP based limiting alone breaks badly behind corporate NAT, where thousands of users share a single egress address.

## audio_01_rate_limiter__k3 [keyword] Retry-After header
_origin: drafted_
- `audio_01_rate_limiter#40` SPEAKER_00 312.7s: Now the response contract. On rejection we return status four twenty nine, too many requests, with a Retry-After header.

## audio_01_rate_limiter__k4 [keyword] sliding window log
_origin: drafted_
- `audio_01_rate_limiter#10` SPEAKER_00 76.9s: The sliding window log fixes that precisely. We store a timestamp for every request and count the entries inside the trailing sixty seconds.

## audio_01_rate_limiter__k5 [keyword] availability zone
_origin: drafted_
- `audio_01_rate_limiter#26` SPEAKER_00 206.6s: That means the Redis cluster should be in the same region and ideally the same availability zone group as the gateway fleet.

## audio_01_rate_limiter__k6 [keyword] jittered exponential backoff
_origin: drafted_
- `audio_01_rate_limiter#43` SPEAKER_01 336.9s: We should also recommend jittered exponential backoff in the client documentation, otherwise every rejected client retries at the same reset instant.

## audio_01_rate_limiter__k7 [keyword] sub counters
_origin: drafted_
- `audio_01_rate_limiter#30` SPEAKER_00 234.0s: For that case we can shard the counter itself, splitting the limit across a few sub counters and picking one at random per request.
- `audio_01_rate_limiter#31` SPEAKER_01 241.4s: That reduces contention at the cost of some accuracy, because the sub counters drift and one may exhaust before the others.

## audio_01_rate_limiter__k8 [keyword] weighted cost model
_origin: drafted_
- `audio_01_rate_limiter#48` SPEAKER_00 378.0s: A weighted cost model handles that well. A search request spends five tokens while a simple read spends one.

## audio_01_rate_limiter__s1 [semantic] What burst problem does a fixed window counter allow, and how large can the burst be?
_origin: all.json:audio_01_rate_limiter__q1_
- `audio_01_rate_limiter#7` SPEAKER_01 53.8s: Fixed windows are cheap and easy to reason about, but they allow a burst of double the limit at the window boundary.
- `audio_01_rate_limiter#8` SPEAKER_00 60.0s: Exactly. A client can send one hundred requests at the last second of one minute and another hundred at the first second of the next.

## audio_01_rate_limiter__s2 [semantic] Why is the sliding window counter preferred over the sliding window log for a high volume API?
_origin: all.json:audio_01_rate_limiter__q2_
- `audio_01_rate_limiter#10` SPEAKER_00 76.9s: The sliding window log fixes that precisely. We store a timestamp for every request and count the entries inside the trailing sixty seconds.
- `audio_01_rate_limiter#12` SPEAKER_00 94.4s: So the practical middle ground is the sliding window counter, where we blend the previous window and the current window using a weighted average.
- `audio_01_rate_limiter#13` SPEAKER_01 102.0s: That gives us accuracy within a small error margin while storing only two integers per key, which is a good trade for a high volume API.

## audio_01_rate_limiter__s3 [semantic] What token bucket configuration matches the one hundred requests per minute policy, and why is the bucket capped?
_origin: all.json:audio_01_rate_limiter__q3_
- `audio_01_rate_limiter#17` SPEAKER_01 133.1s: We should cap the bucket so idle clients cannot accumulate an unlimited burst. Capacity of one hundred with a refill of one point six seven tokens per second matches our policy.

## audio_01_rate_limiter__s4 [semantic] Why is a Lua script needed on Redis, and what specific race does it prevent?
_origin: all.json:audio_01_rate_limiter__q4_
- `audio_01_rate_limiter#21` SPEAKER_01 168.8s: We should do the whole check and decrement inside a single Lua script so the read, the compare and the write are atomic on the Redis side.
- `audio_01_rate_limiter#22` SPEAKER_00 176.2s: That avoids the classic race where two gateway nodes both read ninety nine and both decide to allow the request.
- `audio_01_rate_limiter#23` SPEAKER_01 182.3s: For the token bucket the script would compute the elapsed time since the last refill, add the earned tokens, clamp to capacity, then try to spend one.

## audio_01_rate_limiter__s5 [semantic] What is the fail open versus fail closed policy when Redis is unreachable, and what is the risk of the local fallback?
_origin: all.json:audio_01_rate_limiter__q5_
- `audio_01_rate_limiter#37` SPEAKER_01 286.9s: For a public API I would fail open for normal endpoints, but fail closed for expensive or sensitive ones like account creation and bulk export.
- `audio_01_rate_limiter#38` SPEAKER_00 296.3s: We should also degrade to a local in memory limiter when the shared store is down, so there is still some ceiling rather than none at all.
- `audio_01_rate_limiter#39` SPEAKER_01 303.4s: Good. The local fallback should use a conservative limit, since each node enforces it independently and the effective total is multiplied by the fleet size.

## audio_01_rate_limiter__s6 [semantic] how do we stop one misbehaving customer from overloading a single server
_origin: drafted_
- `audio_01_rate_limiter#29` SPEAKER_01 226.3s: But a single abusive client is still a single key, and a single key always lands on a single node. That is our hot key problem.
- `audio_01_rate_limiter#30` SPEAKER_00 234.0s: For that case we can shard the counter itself, splitting the limit across a few sub counters and picking one at random per request.

## audio_01_rate_limiter__s7 [semantic] what should happen when many rejected clients all come back at the same moment
_origin: drafted_
- `audio_01_rate_limiter#43` SPEAKER_01 336.9s: We should also recommend jittered exponential backoff in the client documentation, otherwise every rejected client retries at the same reset instant.
- `audio_01_rate_limiter#44` SPEAKER_00 346.0s: That synchronized retry storm is a real failure mode. Jitter spreads the recovery traffic instead of creating a second spike.

## audio_02_url_shortener__k1 [keyword] Feistel network
_origin: drafted_
- `audio_02_url_shortener#15` SPEAKER_01 110.8s: A Feistel network or simple multiplicative inverse modulo the key space works well for that. Unique, unguessable in practice, and no collision check needed.

## audio_02_url_shortener__k2 [keyword] power law
_origin: drafted_
- `audio_02_url_shortener#26` SPEAKER_00 195.5s: For the read path, a cache in front of the store is essential. Link popularity follows a strong power law.

## audio_02_url_shortener__k3 [keyword] interstitial warning page
_origin: drafted_
- `audio_02_url_shortener#40` SPEAKER_00 296.8s: We should also support an interstitial warning page for links flagged as suspicious, rather than a hard block in every case.

## audio_02_url_shortener__k4 [keyword] custom aliases
_origin: drafted_
- `audio_02_url_shortener#6` SPEAKER_00 40.3s: We should also support custom aliases, because marketing teams always want a readable code instead of a random string.
- `audio_02_url_shortener#46` SPEAKER_00 339.9s: What about custom aliases colliding with generated codes? We need one namespace and a reservation mechanism.
- `audio_02_url_shortener#47` SPEAKER_01 346.4s: I would reserve a separate prefix or length for custom aliases, so generated codes can never collide with user chosen ones.

## audio_02_url_shortener__k5 [keyword] range allocator
_origin: drafted_
- `audio_02_url_shortener#18` SPEAKER_00 136.0s: For the unique counter we could use a range allocator. Each application node grabs a block of a million identifiers and serves them locally.

## audio_02_url_shortener__k6 [keyword] reputation service
_origin: drafted_
- `audio_02_url_shortener#39` SPEAKER_01 287.3s: We need to scan submitted URLs against a reputation service at creation time, and rescan periodically because a clean domain can turn malicious later.

## audio_02_url_shortener__k7 [keyword] read replicas
_origin: drafted_
- `audio_02_url_shortener#42` SPEAKER_00 310.0s: For availability, the redirect path must survive a regional failure. That argues for read replicas in multiple regions.
- `audio_02_url_shortener#49` SPEAKER_01 362.9s: Plus temporary redirects to preserve analytics, an asynchronous click pipeline, multi region read replicas and an abuse scanning layer.

## audio_02_url_shortener__s1 [semantic] What encoding and code length are chosen, and how many combinations does that provide?
_origin: all.json:audio_02_url_shortener__q1_
- `audio_02_url_shortener#9` SPEAKER_01 60.4s: Base sixty two, using digits and both letter cases. Seven characters gives about three point five trillion combinations, which is far beyond our needs.
- `audio_02_url_shortener#10` SPEAKER_00 70.4s: Seven is a good default, but we could start at six and grow. Six characters is already fifty six billion possibilities.

## audio_02_url_shortener__s2 [semantic] Why is a temporary redirect used instead of a permanent one?
_origin: all.json:audio_02_url_shortener__q2_
- `audio_02_url_shortener#32` SPEAKER_00 239.4s: Three oh two, because a permanent redirect is cached by the browser and we would never see the subsequent clicks.
- `audio_02_url_shortener#33` SPEAKER_01 245.7s: Right, and we would lose analytics entirely for repeat visitors. The small extra load is worth keeping the data.

## audio_02_url_shortener__s3 [semantic] What is the drawback of encoding a sequential counter, and how is it mitigated while staying collision free?
_origin: all.json:audio_02_url_shortener__q3_
- `audio_02_url_shortener#13` SPEAKER_01 94.6s: But sequential integers leak information. Anyone can enumerate codes and walk the entire database of links, which is a privacy problem.
- `audio_02_url_shortener#14` SPEAKER_00 103.1s: We can mitigate that by scrambling the counter with a reversible permutation before encoding, so the codes look random but remain unique.
- `audio_02_url_shortener#15` SPEAKER_01 110.8s: A Feistel network or simple multiplicative inverse modulo the key space works well for that. Unique, unguessable in practice, and no collision check needed.

## audio_02_url_shortener__s4 [semantic] How does the range allocator assign identifiers, and what is its accepted cost?
_origin: all.json:audio_02_url_shortener__q4_
- `audio_02_url_shortener#18` SPEAKER_00 136.0s: For the unique counter we could use a range allocator. Each application node grabs a block of a million identifiers and serves them locally.
- `audio_02_url_shortener#20` SPEAKER_00 150.7s: The cost is gaps in the sequence when a node restarts, but gaps do not matter at all for our use case.

## audio_02_url_shortener__s5 [semantic] Why is cache invalidation treated as urgent rather than relying on expiry alone?
_origin: all.json:audio_02_url_shortener__q5_
- `audio_02_url_shortener#29` SPEAKER_01 217.8s: Deleted links matter. If someone takes down a malicious link, a stale cache entry keeps serving it, so invalidation needs to be prompt.
- `audio_02_url_shortener#30` SPEAKER_00 226.6s: We can publish invalidation events on a message bus and have every cache node subscribe, rather than relying purely on expiry.

## audio_02_url_shortener__s6 [semantic] why not write click statistics to the database while redirecting the user
_origin: drafted_
- `audio_02_url_shortener#34` SPEAKER_00 252.5s: Now the analytics pipeline. We should not write to the database synchronously on the redirect path.
- `audio_02_url_shortener#35` SPEAKER_01 258.3s: Definitely not. We emit a click event to a queue, return the redirect immediately, and let a consumer aggregate asynchronously.

## audio_02_url_shortener__s7 [semantic] how do we keep bad actors from using short links to spread scams
_origin: drafted_
- `audio_02_url_shortener#38` SPEAKER_00 281.4s: Let's cover abuse, since URL shorteners are a favorite tool for phishing and malware distribution.
- `audio_02_url_shortener#39` SPEAKER_01 287.3s: We need to scan submitted URLs against a reputation service at creation time, and rescan periodically because a clean domain can turn malicious later.

## audio_02_url_shortener__s8 [semantic] how much disk space does the link data need each year
_origin: drafted_
- `audio_02_url_shortener#24` SPEAKER_00 181.1s: Ten million links per month is a hundred and twenty million a year, and each row is maybe five hundred bytes with the URL.
- `audio_02_url_shortener#25` SPEAKER_01 187.7s: So around sixty gigabytes per year of primary data, which is small. The analytics events will be much larger than the link table.

## audio_03_chat_system__k1 [keyword] WebSocket
_origin: drafted_
- `audio_03_chat_system#5` SPEAKER_01 33.0s: Let's start with the connection layer. For real time delivery we need a persistent connection, so WebSocket is the natural choice.
- `audio_03_chat_system#6` SPEAKER_00 40.9s: Long polling is the fallback for restrictive networks, but WebSocket over TLS on port four four three passes through most corporate proxies.
- `audio_03_chat_system#49` SPEAKER_01 348.1s: To summarize, durable write before acknowledgment, WebSocket gateways with a session registry, conversation partitioned storage and client driven catch up.

## audio_03_chat_system__k2 [keyword] session registry
_origin: drafted_
- `audio_03_chat_system#8` SPEAKER_00 57.0s: We need a session registry that maps each user to the gateway node currently holding their connection.
- `audio_03_chat_system#39` SPEAKER_01 280.2s: Then the session registry maps a user to a set of connections, and delivery fans out to all active devices.
- `audio_03_chat_system#49` SPEAKER_01 348.1s: To summarize, durable write before acknowledgment, WebSocket gateways with a session registry, conversation partitioned storage and client driven catch up.

## audio_03_chat_system__k3 [keyword] thundering herd
_origin: drafted_
- `audio_03_chat_system#46` SPEAKER_00 327.8s: All those clients reconnect at once, so we need randomized reconnect delays or we create a thundering herd against the remaining nodes.

## audio_03_chat_system__k4 [keyword] typing indicators
_origin: drafted_
- `audio_03_chat_system#30` SPEAKER_00 216.2s: Let's cover read receipts and typing indicators, because they generate far more traffic than the messages themselves.
- `audio_03_chat_system#31` SPEAKER_01 222.7s: Typing indicators should be ephemeral and never persisted. Send them over the socket with a short expiry and drop them under load.

## audio_03_chat_system__k5 [keyword] read receipts
_origin: drafted_
- `audio_03_chat_system#30` SPEAKER_00 216.2s: Let's cover read receipts and typing indicators, because they generate far more traffic than the messages themselves.
- `audio_03_chat_system#32` SPEAKER_00 229.8s: Read receipts can be batched. Instead of one event per message, the client reports the highest sequence it has read.

## audio_03_chat_system__k6 [keyword] end to end encryption
_origin: drafted_
- `audio_03_chat_system#41` SPEAKER_01 293.7s: What about end to end encryption? That changes the server's role significantly.
- `audio_03_chat_system#42` SPEAKER_00 298.6s: With end to end encryption the server stores ciphertext and cannot build server side search or content moderation on the message body.

## audio_03_chat_system__k7 [keyword] long polling
_origin: drafted_
- `audio_03_chat_system#6` SPEAKER_00 40.9s: Long polling is the fallback for restrictive networks, but WebSocket over TLS on port four four three passes through most corporate proxies.

## audio_03_chat_system__k8 [keyword] clustering key
_origin: drafted_
- `audio_03_chat_system#18` SPEAKER_00 126.3s: I would model messages by conversation. The partition key is the conversation identifier and the clustering key is a monotonically increasing message sequence.

## audio_03_chat_system__s1 [semantic] What is the required ordering between persisting a message and acknowledging the sender, and why?
_origin: all.json:audio_03_chat_system__q1_
- `audio_03_chat_system#3` SPEAKER_01 17.6s: So durability before acknowledgment. The server writes the message to persistent storage first, then returns an acknowledgment to the sender.
- `audio_03_chat_system#4` SPEAKER_00 26.1s: That is the key ordering. If we acknowledge first and write later, a crash loses messages that the user believes were sent.

## audio_03_chat_system__s2 [semantic] What happens when a message is forwarded to a gateway node that no longer owns the user's connection?
_origin: all.json:audio_03_chat_system__q2_
- `audio_03_chat_system#14` SPEAKER_00 97.8s: Stale entries cause messages to be forwarded to a node that no longer owns the connection, so that node must drop and let the store handle it.
- `audio_03_chat_system#15` SPEAKER_01 105.5s: Since the message is already durable, a lost push is only a latency problem. The client will fetch it on reconnect and nothing is truly lost.
- `audio_03_chat_system#16` SPEAKER_00 113.9s: That is the important invariant. Real time delivery is best effort on top of a durable log, not the source of truth.

## audio_03_chat_system__s3 [semantic] How are group messages fanned out, and what determines the approach?
_origin: all.json:audio_03_chat_system__q3_
- `audio_03_chat_system#28` SPEAKER_00 200.7s: So a hybrid. Below a member threshold we write per user entries, above it we keep one copy and have clients read the conversation directly.
- `audio_03_chat_system#29` SPEAKER_01 209.1s: That mirrors the approach used in social feeds, and the threshold becomes a tuning knob we can adjust from configuration.

## audio_03_chat_system__s4 [semantic] How are typing indicators and read receipts made cheap, given they generate more traffic than messages?
_origin: all.json:audio_03_chat_system__q4_
- `audio_03_chat_system#31` SPEAKER_01 222.7s: Typing indicators should be ephemeral and never persisted. Send them over the socket with a short expiry and drop them under load.
- `audio_03_chat_system#32` SPEAKER_00 229.8s: Read receipts can be batched. Instead of one event per message, the client reports the highest sequence it has read.
- `audio_03_chat_system#33` SPEAKER_01 236.4s: That collapses a hundred events into one and is exactly equivalent, since reading is monotonic within a conversation.

## audio_03_chat_system__s5 [semantic] Why can messages not be ordered by the sender's timestamp, and what is used instead?
_origin: all.json:audio_03_chat_system__q5_
- `audio_03_chat_system#22` SPEAKER_00 157.9s: Sequencing inside a conversation is subtle. Client clocks are unreliable, so we cannot order by the sender's timestamp.
- `audio_03_chat_system#23` SPEAKER_01 165.3s: The server assigns the sequence number per conversation, which gives a total order that all participants agree on.
- `audio_03_chat_system#25` SPEAKER_01 178.8s: And clients need to handle out of order arrival gracefully, inserting by sequence rather than by arrival time.

## audio_03_chat_system__s6 [semantic] what if the person receiving the message is not online
_origin: drafted_
- `audio_03_chat_system#12` SPEAKER_00 83.8s: If B is offline, we skip the push and rely on the stored message plus a mobile push notification through the platform services.

## audio_03_chat_system__s7 [semantic] how does it work when someone uses the app on their phone and laptop at once
_origin: drafted_
- `audio_03_chat_system#38` SPEAKER_00 272.1s: We should also think about multiple devices. The same user may have a phone, a tablet and a desktop client connected simultaneously.
- `audio_03_chat_system#39` SPEAKER_01 280.2s: Then the session registry maps a user to a set of connections, and delivery fans out to all active devices.
- `audio_03_chat_system#40` SPEAKER_00 286.9s: Read state also becomes per user rather than per device, so marking a message read on the phone clears it on the laptop.

## audio_04_news_feed__k1 [keyword] reverse chronological
_origin: drafted_
- `audio_04_news_feed#18` SPEAKER_00 124.5s: Now ranking. The simplest feed is reverse chronological, which is predictable and needs no machine learning.

## audio_04_news_feed__k2 [keyword] adjacency lists
_origin: drafted_
- `audio_04_news_feed#39` SPEAKER_01 274.5s: We store followers and following as separate adjacency lists, because the two directions are queried in different code paths.

## audio_04_news_feed__k3 [keyword] cold start
_origin: drafted_
- `audio_04_news_feed#41` SPEAKER_01 289.2s: Let's cover the cold start case. A brand new user follows nobody, so their feed is empty.

## audio_04_news_feed__k4 [keyword] fan out lag
_origin: drafted_
- `audio_04_news_feed#43` SPEAKER_01 303.4s: For observability, we should track feed latency, cache hit ratio, fan out lag and the fraction of the feed that comes from the read path merge.
- `audio_04_news_feed#44` SPEAKER_00 312.3s: Fan out lag is the key health metric. If it grows, users see stale feeds even though nothing is technically broken.

## audio_04_news_feed__k5 [keyword] candidate generation
_origin: drafted_
- `audio_04_news_feed#20` SPEAKER_00 138.3s: The typical pipeline has three stages. Candidate generation, then a lightweight ranking pass, then a heavier model on the survivors.
- `audio_04_news_feed#21` SPEAKER_01 146.5s: Candidate generation might produce a few thousand posts, the light ranker cuts that to a few hundred, and the heavy ranker orders the final page.

## audio_04_news_feed__k6 [keyword] diversity rules
_origin: drafted_
- `audio_04_news_feed#24` SPEAKER_00 170.0s: We should also apply diversity rules after ranking, so the feed does not show ten consecutive posts from the same author.

## audio_04_news_feed__k7 [keyword] stable cursor
_origin: drafted_
- `audio_04_news_feed#28` SPEAKER_00 197.9s: Pagination needs a stable cursor, because if we paginate by offset the list shifts under the user as new posts arrive.

## audio_04_news_feed__s1 [semantic] What follower threshold flags an account as a celebrity, and how are those accounts handled?
_origin: all.json:audio_04_news_feed__q1_
- `audio_04_news_feed#8` SPEAKER_00 54.3s: We set a threshold, maybe a hundred thousand followers, above which an account is flagged as a celebrity and excluded from push.
- `audio_04_news_feed#9` SPEAKER_01 61.7s: At read time we take the precomputed feed, pull recent posts from the celebrities the viewer follows, and merge the two lists.
- `audio_04_news_feed#11` SPEAKER_01 74.9s: We should cache the celebrity timelines aggressively, since millions of viewers pull the same few author timelines.

## audio_04_news_feed__s2 [semantic] Why does the feed store only post references instead of post content?
_origin: all.json:audio_04_news_feed__q2_
- `audio_04_news_feed#14` SPEAKER_00 96.2s: We do not store post content in the feed, only references, so an edit or deletion takes effect everywhere immediately.
- `audio_04_news_feed#15` SPEAKER_01 103.5s: Hydration happens at read time, fetching the actual post objects in a batch from the post store or cache.
- `audio_04_news_feed#17` SPEAKER_01 117.9s: Without that, a deleted post would linger in millions of precomputed feeds and we would have to chase it down with deletes.

## audio_04_news_feed__s3 [semantic] Describe the ranking funnel and explain why it keeps latency acceptable.
_origin: all.json:audio_04_news_feed__q3_
- `audio_04_news_feed#20` SPEAKER_00 138.3s: The typical pipeline has three stages. Candidate generation, then a lightweight ranking pass, then a heavier model on the survivors.
- `audio_04_news_feed#22` SPEAKER_00 155.1s: That staged funnel is what keeps latency acceptable, because the expensive model only ever sees a small candidate set.
- `audio_04_news_feed#24` SPEAKER_00 170.0s: We should also apply diversity rules after ranking, so the feed does not show ten consecutive posts from the same author.

## audio_04_news_feed__s4 [semantic] How is fan out work reduced for users who rarely open the app?
_origin: all.json:audio_04_news_feed__q4_
- `audio_04_news_feed#32` SPEAKER_00 226.5s: We should prioritize active followers first, so people likely to open the app soon get the post before dormant accounts.
- `audio_04_news_feed#34` SPEAKER_00 241.1s: In fact for dormant users we could skip the push entirely and rebuild their feed on read when they eventually return.

## audio_04_news_feed__s5 [semantic] Why are feeds treated as cache, and which metric is recommended for alerting?
_origin: all.json:audio_04_news_feed__q5_
- `audio_04_news_feed#36` SPEAKER_00 254.4s: Storage wise, feeds are pure cache. We can always rebuild them from the posts and the follow graph if we lose them.
- `audio_04_news_feed#45` SPEAKER_01 319.0s: We should alert on that lag rather than on worker queue depth, because lag directly maps to user experience.

## audio_04_news_feed__s6 [semantic] what does a new user see before following anyone
_origin: drafted_
- `audio_04_news_feed#41` SPEAKER_01 289.2s: Let's cover the cold start case. A brand new user follows nobody, so their feed is empty.
- `audio_04_news_feed#42` SPEAKER_00 295.3s: We fill it with popular and topical content based on declared interests, and gradually shift to graph based content as they follow accounts.

## audio_04_news_feed__s7 [semantic] how do we avoid showing the same post twice while scrolling
_origin: drafted_
- `audio_04_news_feed#28` SPEAKER_00 197.9s: Pagination needs a stable cursor, because if we paginate by offset the list shifts under the user as new posts arrive.
- `audio_04_news_feed#29` SPEAKER_01 204.8s: A cursor encoding the last seen position and the ranking snapshot avoids duplicates and gaps when scrolling.

## audio_04_news_feed__s8 [semantic] what happens to a removed post that was already pushed to many timelines
_origin: drafted_
- `audio_04_news_feed#14` SPEAKER_00 96.2s: We do not store post content in the feed, only references, so an edit or deletion takes effect everywhere immediately.
- `audio_04_news_feed#16` SPEAKER_00 110.0s: That also lets us filter at read time. Blocked authors, deleted posts and changed privacy settings are all applied during hydration.
- `audio_04_news_feed#17` SPEAKER_01 117.9s: Without that, a deleted post would linger in millions of precomputed feeds and we would have to chase it down with deletes.

## audio_05_payment_idempotency__k1 [keyword] idempotency key
_origin: drafted_
- `audio_05_payment_idempotency#3` SPEAKER_01 19.9s: That help is the idempotency key. The client generates a unique key per logical payment attempt and sends it with every retry.
- `audio_05_payment_idempotency#50` SPEAKER_00 349.4s: To summarize, scoped idempotency keys with request fingerprinting, intent before external call, and reconciliation by merchant reference.

## audio_05_payment_idempotency__k2 [keyword] double entry ledger
_origin: drafted_
- `audio_05_payment_idempotency#25` SPEAKER_01 176.3s: Let's talk about the ledger. The payment state is operational, but the accounting truth should be a double entry ledger.
- `audio_05_payment_idempotency#51` SPEAKER_01 358.1s: Plus a validated state machine, an immutable double entry ledger, sagas with compensation and a transactional outbox for events.

## audio_05_payment_idempotency__k3 [keyword] transactional outbox
_origin: drafted_
- `audio_05_payment_idempotency#36` SPEAKER_00 254.7s: For reliability between services we should use the transactional outbox pattern rather than publishing events directly.
- `audio_05_payment_idempotency#51` SPEAKER_01 358.1s: Plus a validated state machine, an immutable double entry ledger, sagas with compensation and a transactional outbox for events.

## audio_05_payment_idempotency__k4 [keyword] merchant reference
_origin: drafted_
- `audio_05_payment_idempotency#16` SPEAKER_00 113.6s: That is why every processor supports a merchant reference. It lets us ask, did you already process this, rather than guessing.
- `audio_05_payment_idempotency#50` SPEAKER_00 349.4s: To summarize, scoped idempotency keys with request fingerprinting, intent before external call, and reconciliation by merchant reference.

## audio_05_payment_idempotency__k5 [keyword] optimistic concurrency
_origin: drafted_
- `audio_05_payment_idempotency#20` SPEAKER_00 144.4s: Storing the state machine in the database with a version column gives us optimistic concurrency on transitions.

## audio_05_payment_idempotency__k6 [keyword] tokenization
_origin: drafted_
- `audio_05_payment_idempotency#44` SPEAKER_00 306.4s: Tokenization through the processor keeps us out of the strictest compliance scope, and we only hold an opaque token.

## audio_05_payment_idempotency__k7 [keyword] webhook signatures
_origin: drafted_
- `audio_05_payment_idempotency#42` SPEAKER_00 293.2s: We also need to verify webhook signatures, since the endpoint is publicly reachable and an attacker could forge a success event.

## audio_05_payment_idempotency__k8 [keyword] floating point
_origin: drafted_
- `audio_05_payment_idempotency#22` SPEAKER_00 156.6s: For the money itself, we store amounts as integers in the smallest currency unit, never as floating point.
- `audio_05_payment_idempotency#23` SPEAKER_01 162.8s: Absolutely. Floating point rounding in financial code is a guaranteed source of penny discrepancies that auditors will find.

## audio_05_payment_idempotency__s1 [semantic] How must an idempotency key be scoped and validated?
_origin: all.json:audio_05_payment_idempotency__q1_
- `audio_05_payment_idempotency#5` SPEAKER_01 34.6s: We must scope the key to the account, otherwise one customer could guess another customer's key and read their payment result.
- `audio_05_payment_idempotency#6` SPEAKER_00 41.6s: And we should hash the request body and compare it, so the same key with different parameters is rejected as a conflict.

## audio_05_payment_idempotency__s2 [semantic] What is the correct ordering around the external processor call, and how is a crash recovered?
_origin: all.json:audio_05_payment_idempotency__q2_
- `audio_05_payment_idempotency#14` SPEAKER_00 96.3s: So the sequence is, persist intent, call the processor, persist the outcome. Recovery finds intents without outcomes and reconciles.
- `audio_05_payment_idempotency#15` SPEAKER_01 105.2s: Reconciliation queries the processor by our own reference identifier, which we must pass on the outbound call for exactly this purpose.
- `audio_05_payment_idempotency#17` SPEAKER_01 121.2s: And we should never blindly retry an outbound charge without first checking, because that is the direct path to a double charge.

## audio_05_payment_idempotency__s3 [semantic] How are concurrent retries with the same key handled?
_origin: all.json:audio_05_payment_idempotency__q3_
- `audio_05_payment_idempotency#9` SPEAKER_01 61.5s: So the key record needs a state machine. We insert it as in progress with a unique constraint, and the loser of that race waits or returns a conflict.
- `audio_05_payment_idempotency#10` SPEAKER_00 70.6s: I would return a four oh nine with a retry hint rather than blocking, because holding a request open ties up resources.

## audio_05_payment_idempotency__s4 [semantic] Why is a saga used instead of two phase commit, and what does compensation actually mean here?
_origin: all.json:audio_05_payment_idempotency__q4_
- `audio_05_payment_idempotency#32` SPEAKER_00 225.3s: Two phase commit across service boundaries is not practical here, so we use a saga with compensating actions.
- `audio_05_payment_idempotency#34` SPEAKER_00 240.1s: Compensation for a capture is a refund, and compensation for an inventory reservation is a release. Neither is a true rollback.
- `audio_05_payment_idempotency#35` SPEAKER_01 247.9s: That is the key mental shift. Sagas give eventual consistency with business level undo, not atomicity.

## audio_05_payment_idempotency__s5 [semantic] What does the transactional outbox solve, and what does it require of consumers?
_origin: all.json:audio_05_payment_idempotency__q5_
- `audio_05_payment_idempotency#37` SPEAKER_01 261.4s: So the state change and the outgoing event are written in the same local transaction, and a relay publishes from the outbox.
- `audio_05_payment_idempotency#38` SPEAKER_00 268.7s: That eliminates the failure mode where we commit the charge but crash before publishing the event.
- `audio_05_payment_idempotency#39` SPEAKER_01 273.8s: Consumers must then be idempotent, because the relay guarantees at least once delivery and duplicates are normal.

## audio_05_payment_idempotency__s6 [semantic] why should money never be stored as numbers with fractional decimals
_origin: drafted_
- `audio_05_payment_idempotency#22` SPEAKER_00 156.6s: For the money itself, we store amounts as integers in the smallest currency unit, never as floating point.
- `audio_05_payment_idempotency#23` SPEAKER_01 162.8s: Absolutely. Floating point rounding in financial code is a guaranteed source of penny discrepancies that auditors will find.

## audio_05_payment_idempotency__s7 [semantic] what if our card processor goes down entirely
_origin: drafted_
- `audio_05_payment_idempotency#48` SPEAKER_00 335.0s: We should also support multiple processors with failover, since a single processor outage would otherwise stop all revenue.
- `audio_05_payment_idempotency#49` SPEAKER_01 342.0s: Routing between them needs care, because an in flight payment must not be retried on a different processor without a status check.

## audio_06_video_streaming__k1 [keyword] pre signed URL
_origin: drafted_
- `audio_06_video_streaming#4` SPEAKER_00 28.0s: Direct to storage upload with a pre signed URL keeps the file bytes out of our application servers entirely.

## audio_06_video_streaming__k2 [keyword] fixed keyframe interval
_origin: drafted_
- `audio_06_video_streaming#12` SPEAKER_00 83.9s: Exactly. Misaligned keyframes cause visible glitches or failed switches, so the encoder must be configured with a fixed keyframe interval.

## audio_06_video_streaming__k3 [keyword] RTMP
_origin: drafted_
- `audio_06_video_streaming#34` SPEAKER_00 236.7s: The ingest is a continuous stream rather than a file, using a protocol like RTMP or a low latency variant.

## audio_06_video_streaming__k4 [keyword] rebuffer ratio
_origin: drafted_
- `audio_06_video_streaming#42` SPEAKER_00 291.8s: Startup time, rebuffer ratio, average bitrate and playback failures are the four numbers that actually describe the experience.
- `audio_06_video_streaming#43` SPEAKER_01 299.4s: Rebuffer ratio is the one users feel most. A slightly lower bitrate is almost always better than a stall.

## audio_06_video_streaming__k5 [keyword] digital rights management
_origin: drafted_
- `audio_06_video_streaming#30` SPEAKER_00 211.8s: And for premium content, digital rights management with license servers, though that adds significant client complexity.

## audio_06_video_streaming__k6 [keyword] preemptible instances
_origin: drafted_
- `audio_06_video_streaming#22` SPEAKER_00 158.2s: Spot or preemptible instances also fit this workload well, since segment level retries make interruption cheap.

## audio_06_video_streaming__k7 [keyword] directed graph
_origin: drafted_
- `audio_06_video_streaming#15` SPEAKER_01 106.4s: We need a job orchestrator with a directed graph of tasks, since thumbnail extraction, audio processing and each rendition can run concurrently.

## audio_06_video_streaming__s1 [semantic] Why upload directly to storage with a pre signed URL instead of through application servers?
_origin: all.json:audio_06_video_streaming__q1_
- `audio_06_video_streaming#4` SPEAKER_00 28.0s: Direct to storage upload with a pre signed URL keeps the file bytes out of our application servers entirely.
- `audio_06_video_streaming#5` SPEAKER_01 34.3s: That is important. Proxying multi gigabyte files through application nodes wastes bandwidth and ties up connections for a long time.

## audio_06_video_streaming__s2 [semantic] What makes adaptive bitrate switching work correctly across renditions?
_origin: all.json:audio_06_video_streaming__q2_
- `audio_06_video_streaming#9` SPEAKER_01 63.6s: And each rendition is segmented into short chunks, typically two to six seconds, with a manifest listing the available variants.
- `audio_06_video_streaming#11` SPEAKER_01 77.0s: That switching only works if the segments are aligned across renditions, with keyframes at identical timestamps.
- `audio_06_video_streaming#12` SPEAKER_00 83.9s: Exactly. Misaligned keyframes cause visible glitches or failed switches, so the encoder must be configured with a fixed keyframe interval.

## audio_06_video_streaming__s3 [semantic] How is transcoding cost controlled for unpopular content?
_origin: all.json:audio_06_video_streaming__q3_
- `audio_06_video_streaming#20` SPEAKER_00 143.8s: So we should encode the full ladder lazily for unpopular content, generating only the most common rendition up front.
- `audio_06_video_streaming#21` SPEAKER_01 150.6s: Then if a video gains traction we backfill the remaining renditions on demand, which avoids paying for content nobody watches.
- `audio_06_video_streaming#22` SPEAKER_00 158.2s: Spot or preemptible instances also fit this workload well, since segment level retries make interruption cheap.

## audio_06_video_streaming__s4 [semantic] How do caching requirements differ between segments and manifests?
_origin: all.json:audio_06_video_streaming__q4_
- `audio_06_video_streaming#26` SPEAKER_00 186.3s: Segment URLs should be stable and immutable, which makes them perfectly cacheable with a very long time to live.
- `audio_06_video_streaming#27` SPEAKER_01 192.7s: Manifests are different. For live content the manifest updates constantly and needs a very short cache lifetime.
- `audio_06_video_streaming#28` SPEAKER_00 199.6s: That split, immutable segments and volatile manifests, is the core caching insight for streaming.

## audio_06_video_streaming__s5 [semantic] Which client side metrics describe playback quality, and which matters most?
_origin: all.json:audio_06_video_streaming__q5_
- `audio_06_video_streaming#42` SPEAKER_00 291.8s: Startup time, rebuffer ratio, average bitrate and playback failures are the four numbers that actually describe the experience.
- `audio_06_video_streaming#44` SPEAKER_00 305.9s: The player's adaptation algorithm should therefore be conservative on the way up and aggressive on the way down.

## audio_06_video_streaming__s6 [semantic] how do we survive a huge premiere when everyone starts watching at once
_origin: drafted_
- `audio_06_video_streaming#31` SPEAKER_01 218.8s: We should also think about pre positioning. For a highly anticipated release we can push content to edges before launch.
- `audio_06_video_streaming#32` SPEAKER_00 226.0s: Otherwise the first wave of viewers all miss cache simultaneously and hammer the origin at exactly the worst moment.

## audio_06_video_streaming__s7 [semantic] how can live broadcasts get closer to real time
_origin: drafted_
- `audio_06_video_streaming#36` SPEAKER_00 251.9s: And latency becomes a first class requirement. Standard segmented streaming adds ten to thirty seconds of delay.
- `audio_06_video_streaming#37` SPEAKER_01 258.7s: Low latency modes use shorter segments and chunked transfer, pushing partial segments before they are complete.
- `audio_06_video_streaming#38` SPEAKER_00 265.4s: That cuts latency to a few seconds, at the cost of less efficient caching and more requests per viewer.

## audio_06_video_streaming__s8 [semantic] what keeps a live broadcast running if the streamer's connection drops
_origin: drafted_
- `audio_06_video_streaming#39` SPEAKER_01 271.2s: We also need a failover path for the ingest, because a dropped encoder connection means dead air for every viewer.
- `audio_06_video_streaming#40` SPEAKER_00 277.8s: Dual ingest from the broadcaster into two regions, with automatic switchover, is the standard answer for important events.
