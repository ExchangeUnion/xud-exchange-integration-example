import decimal
import functools
import xudrpc_pb2
import xudrpc_pb2_grpc
import grpc
import _thread
import traceback
from decimal import Decimal
from termcolor import colored
from time import time
import sys

buy = []
sell = []
user = None

orders = []
users = []
P = 'BTC'
Q = 'LTC'
channel = None
host = 'localhost'
port = 8886
cert = 'tls.cert'

boot_timestamp = time()


class User:
    def __init__(self, name):
        self.name = name
        self.balance = {}
        self.orders = []


class Match:
    def __init__(self, order, quantity, price):
        self.order = order
        self.quantity = quantity
        self.price = price

    def __repr__(self):
        return "Match{order=%s, quantity=%s, price=%s}" % (self.order.id, self.quantity, self.price)


class Order:
    id = 0

    def __init__(self, user, side, quantity, price=None, extra={}):
        Order.id = Order.id + 1
        self.id = Order.id
        self.user = user
        self.side = side
        self.quantity = Decimal(quantity)
        self.original_quantity = Decimal(quantity)
        self.price = Decimal(price) if price is not None else None
        self.matches = []
        self.status = 'PENDING'
        self.reject_reason = None
        self.extra = extra

    def __repr__(self):
        return "Order{id=%s, user=%s, side=%s, quantity=%s/%s, price=%s, status=%s, reject_reason=%s, matches=%s, extra=%s}" % (self.id, self.user.name, self.side, self.quantity, self.original_quantity, self.price, self.status, self.reject_reason, self.matches, self.extra)


# alice = User('alice')
alice = User('satoshi')
alice.balance[P] = Decimal(1)
alice.balance[Q] = Decimal(1)

# bob = User('bob')
bob = User('charlie')
bob.balance[P] = Decimal(1)
bob.balance[Q] = Decimal(1)

xud = User('xud')

users.append(alice)
users.append(bob)


def compare_buy(a, b):
    p = decimal.Decimal.compare(b.price, a.price)
    if p == 0:
        return a.id - b.id
    return p


def compare_sell(a, b):
    p = decimal.Decimal.compare(a.price, b.price)
    if p == 0:
        return a.id - b.id
    return p


def get_peers(order):
    global buy, sell
    
    peers = []

    if order.side == 'buy':
        peers = sell
    elif order.side == 'sell':
        peers = buy
    
    return peers


def accept_price(order, price):
    if order.side == 'buy':
        return order.price >= price
    elif order.side == 'sell':
        return order.price <= price


def do_place(order):
    global buy, sell
    if order.side == 'buy':
        buy.append(order)
        buy = list(sorted(buy, key=functools.cmp_to_key(compare_buy)))
    elif order.side == 'sell':
        sell.append(order)
        sell = list(sorted(sell, key=functools.cmp_to_key(compare_sell)))
    if order.user is not xud:
        xud_place_order(order.id, order.side, order.quantity, order.price)


def do_settlement(order):
    if order.user == xud:
        return
    global P, Q
    for match in order.matches:
        peer = match.order
        if peer.user == xud:
            xud_execute_swap(peer.extra["xud_order_id"], peer.extra["peer_pub_key"], match.quantity)
            total = match.quantity * match.price
            if order.side == 'buy':
                order.user.balance[Q] += match.quantity
                order.user.balance[P] -= total
            elif order.side == 'sell':
                order.user.balance[Q] -= match.quantity
                order.user.balance[P] += total
        else:
            total = match.quantity * match.price
            if order.side == 'buy':
                order.user.balance[Q] += match.quantity
                order.user.balance[P] -= total
                peer.user.balance[Q] -= match.quantity
                peer.user.balance[P] += total
            elif order.side == 'sell':
                order.user.balance[Q] -= match.quantity
                order.user.balance[P] += total
                peer.user.balance[Q] += match.quantity
                peer.user.balance[P] -= total


def handle_market_order(order):
    order.status = 'OPEN'
    
    peers = get_peers(order)
    
    total = 0
    for peer in peers:
        total += peer.quantity
    if total < order.quantity:
        order.status = 'REJECTED'
        order.reject_reason = 'INSUFFICIENT_MARKET_DEPTH'
        print('Insufficient market depth')
        return
    remain = order.quantity
    while len(peers) > 0 and remain > 0:
        first = peers[0]
        if remain >= first.quantity:
            q = first.quantity
            remain = remain - first.quantity
            first.quantity = 0
            first.status = 'CLOSED'
            order.matches.append(Match(order=first, quantity=q, price=first.price))
            peers.pop(0)
        else:
            q = remain
            remain = 0
            first.quantity = first.quantity - remain
            order.matches.append(Match(order=first, quantity=q, price=first.price))

    order.quantity = remain

    order.status = 'CLOSED'

    if len(order.matches) > 0:
        do_settlement(order)

    # print(order)


def handle_limit_order(order):
    global buy, sell
    order.status = 'OPEN'

    peers = get_peers(order)
    
    remain = order.quantity
    while len(peers) > 0 and remain > 0 and accept_price(order, peers[0].price):
        first = peers[0]
        if remain >= first.quantity:
            q = first.quantity
            remain = remain - first.quantity
            first.quantity = 0
            first.status = 'CLOSED'
            order.matches.append(Match(order=first, quantity=q, price=order.price))
            peers.pop(0)
        else:
            q = remain
            remain = 0
            first.quantity = first.quantity - remain
            order.matches.append(Match(order=first, quantity=q, price=order.price))

    order.quantity = remain
    
    if remain > 0:
        # maker here
        do_place(order)
    else:
        order.status = 'CLOSED'
    
    if len(order.matches) > 0:
        do_settlement(order)

    # print(order)
    
    
def place_order(cmd):
    global user, orders
    if user is None:
        print("Login first")
        return
    parts = cmd.split()
    side = parts[0]
    if len(parts) < 2:
        print("Missing <quantity>[@<price>]")
        return
    qp = parts[1]
    if '@' in qp:
        nums = qp.split('@')
        order = Order(user, side, quantity=nums[0], price=nums[1])
        orders.append(order)
        handle_limit_order(order)
    else:
        order = Order(user, side, quantity=qp)
        orders.append(order)
        handle_market_order(order)
    # buy = sorted(buy, key=functools.cmp_to_key(compare_buy))


def place_xud_order(quantity, price, order_id, side, peer_pub_key, created_at):
    order = Order(xud, side, quantity, price, extra={
        "xud_order_id": order_id,
        "peer_pub_key": peer_pub_key,
        "created_at": created_at,
    })
    orders.append(order)
    if price is None:
        handle_market_order(order)
    else:
        handle_limit_order(order)


def cancel_order(cmd):
    global user, orders, buy, sell
    if user is None:
        print("Login first")
        return
    parts = cmd.split()
    if len(parts) < 2:
        print("Missing <orderId>")
    order_id = int(parts[1])
    result = list(filter(lambda x: x.id == order_id, orders))
    if len(result) == 0:
        print("Not found!")
        return
    target = result[0]
    if target.status == 'OPEN':
        target.status = 'CANCELLED'
        if target.side == 'buy':
            buy.remove(target)
        elif target.side == 'sell':
            sell.remove(target)
    else:
        print('Too late to cancel')
        return


def cancel_xud_order(order_id):
    global orders, buy, sell
    result = list(filter(lambda x: "xud_order_id" in x.extra and x.extra["xud_order_id"] == order_id, orders))
    if len(result) == 0:
        print("Not found!")
        return
    target = result[0]
    if target.status == 'OPEN':
        target.status = 'CANCELLED'
        if target.side == 'buy':
            buy.remove(target)
        elif target.side == 'sell':
            sell.remove(target)
    else:
        print('Too late to cancel')
        return


def print_order_entry(order):
    text = '   %-13s%s' % (order.price, order.quantity)
    if order.side == 'sell':
        if order.user == xud:
            print(colored(text, 'red'))
        else:
            print(colored(text, 'red', attrs=['dark']))
    elif order.side == 'buy':
        if order.user == xud:
            print(colored(text, 'green'))
        else:
            print(colored(text, 'green', attrs=['dark']))


def print_orderbook():
    print("============================")
    print(" Price(%s)   Quantity(%s) " % (Q, P))
    print("----------------------------")
    for e in reversed(sell):
        print_order_entry(e)
    for e in buy:
        print_order_entry(e)
    print("============================")


def load_credentials(cert = './tls.cert'):
    with open(cert, 'rb') as f:
        cert = f.read()
    return grpc.ssl_channel_credentials(root_certificates=cert)  # Need binary cert not string!


def xud_list_pairs():
    global channel
    if channel is None:
        return
    stub = xudrpc_pb2_grpc.XudStub(channel)
    request = xudrpc_pb2.ListPairsRequest()
    response = stub.ListPairs(request)
    print('Currency Pairs: %s' % (', '.join(response.pairs)))


def xud_get_info():
    global channel
    if channel is None:
        return
    stub = xudrpc_pb2_grpc.XudStub(channel)
    request = xudrpc_pb2.GetInfoRequest()
    response = stub.GetInfo(request)
    # print(response)
    print('Connected to xud %s pub_key: %s\n' % (response.version, response.node_pub_key))
    xud_list_pairs()
    print('\nBTC Lightning Channels: %s' % (response.lndbtc.channels.active))
    print('LTC Lightning Channels: %s' % (response.lndltc.channels.active))


# def xud_get_orders():
#     global stub
#     request = xudrpc_pb2.GetOrdersRequest(pair_id='LTC/BTC', include_own_orders=True)
#     response = stub.GetOrders(request)
#     print(response)


def xud_place_order(order_id, side, quantity, price):
    global channel, Q, P, boot_timestamp
    if channel is None:
        # print("xud is not connected!")
        return
    stub = xudrpc_pb2_grpc.XudStub(channel)
    xud_side = xudrpc_pb2.BUY if side == 'buy' else xudrpc_pb2.SELL
    request = xudrpc_pb2.PlaceOrderRequest(price=price, quantity=quantity, pair_id='%s/%s' % (Q, P), order_id='test-%s-%s' % (boot_timestamp, order_id), side=xud_side)
    # print('[XUD]PlaceOrder: order_id=%s, side=%s, quantity=%s, price=%s' % (order_id, side, quantity, price))
    for response in stub.PlaceOrder(request):
        print(response)


def xud_execute_swap(order_id, peer_pub_key, quantity):
    global channel, Q, P
    if channel is None:
        # print("xud is not connected!")
        return
    stub = xudrpc_pb2_grpc.XudStub(channel)
    request = xudrpc_pb2.ExecuteSwapRequest(pair_id='%s/%s' % (Q, P), order_id=order_id, peer_pub_key=peer_pub_key, quantity=quantity)
    print('[XUD]ExecuteSwap: order_id=%s, peer_pub_key=%s, quantity=%s' % (order_id, peer_pub_key, quantity))
    response = stub.ExecuteSwap(request)
    print("--------------SWAP--------------")
    print(response)


def subscribe_added_orders():
    global channel
    try:
        stub = xudrpc_pb2_grpc.XudStub(channel)
        request = xudrpc_pb2.SubscribeAddedOrdersRequest(existing=True)
        # print('[XUD]SubscribeAddedOrders')
        for response in stub.SubscribeAddedOrders(request):
            #print("------------ADDED------------")
            #print(response)
            if not response.is_own_order:
                qq = round(response.quantity, 4)
                place_xud_order(str(qq), str(response.price), response.id, 'sell' if response.side == xudrpc_pb2.SELL else 'buy', response.peer_pub_key, response.created_at)
    except:
        print('Failed to subscribe added orders')
        traceback.print_exc()


def subscribe_removed_orders():
    global channel
    try:
        stub = xudrpc_pb2_grpc.XudStub(channel)
        request = xudrpc_pb2.SubscribeRemovedOrdersRequest()
        # print('[XUD]SubscribeRemovedOrders')
        for response in stub.SubscribeRemovedOrders(request):
            #print("-----------REMOVED-----------")
            #print(response)
            cancel_xud_order(response.order_id)
    except:
        print('Failed to subscribe removed orders')
        traceback.print_exc()


# order_id: "323c5320-f9f8-11e8-a0e9-75f4ab14fe23"
# local_id: "test-1544171166.0081122-21"
# pair_id: "LTC/BTC"
# quantity: 1.0
# r_hash: "5989278d46c6c338b67fca51811b8f4bcf153e63fd05690a2b7d0e13e71ac657"
# amount_received: 780000
# amount_sent: 100000000
# peer_pub_key: "028fd9e98ca12820aab1ce974c8de42d6b75327a38de5603ff6f2cf87f529b4808"
# role: MAKER
# currency_received: "BTC"
# currency_sent: "LTC"

def handle_xud_swap(swap):
    global orders, buy, sell, P, Q
    order_id = int(swap.local_id[23:])
    # print('order_id', order_id)
    q = Decimal(str(swap.quantity))
    result = list(filter(lambda x: x.id == order_id, orders))
    if len(result) == 0:
        print('Not found such order %s for swap %s' % (order_id, swap))
        return
    order = result[0]

    # print(order)

    if order.quantity > q:
        order.quantity -= q
    else:
        order.quantity = 0
        order.status = 'CLOSED'
        if order.side == 'buy':
            buy.remove(order)
        elif order.side == 'sell':
            sell.remove(order)

    # change user balance here
    if order.side == 'buy':
        order.user.balance[P] -= Decimal(str(swap.amount_sent)) / Decimal('100000000')
        order.user.balance[Q] += Decimal(str(swap.amount_received)) / Decimal('100000000')
    elif order.side == 'sell':
        order.user.balance[Q] -= Decimal(str(swap.amount_sent)) / Decimal('100000000')
        order.user.balance[P] += Decimal(str(swap.amount_received)) / Decimal('100000000')


def subscribe_swaps():
    global channel
    try:
        stub = xudrpc_pb2_grpc.XudStub(channel)
        request = xudrpc_pb2.SubscribeSwapsRequest()
        # print('[XUD]SubscribeSwaps')
        for response in stub.SubscribeSwaps(request):
            print("------------SWAPS------------")
            print(response)
            handle_xud_swap(response)
    except:
        print('Failed to subscribe swaps')
        traceback.print_exc()


# def run_subscribe_added_orders(host, port):
#     # with grpc.secure_channel('%s:%s' % (host, port), load_credentials()) as channel:
#     global channel
#     stub = xudrpc_pb2_grpc.XudStub(channel)
#     subscribe_added_orders(stub)


# def run_subscribe_removed_orders(host, port):
#     # with grpc.secure_channel('%s:%s' % (host, port), load_credentials()) as channel:
#     global channel
#     stub = xudrpc_pb2_grpc.XudStub(channel)
#     subscribe_removed_orders(stub)


# def run_subscribe_swaps(host, port):
#     # with grpc.secure_channel('%s:%s' % (host, port), load_credentials()) as channel:
#     global channel
#     stub = xudrpc_pb2_grpc.XudStub(channel)
#     subscribe_swaps(stub)


def handle_connect(cmd):
    global channel, host, port, cert

    # parts = cmd.split()
    # host = parts[1] if len(parts) > 1 else 'localhost'
    # port = parts[2] if len(parts) > 2 else 8886
    # cert = parts[3] if len(parts) > 3 else './tls.cert'

    try:
        channel = grpc.secure_channel('%s:%s' % (host, port), load_credentials(cert))
        _thread.start_new_thread(subscribe_added_orders, ())
        _thread.start_new_thread(subscribe_removed_orders, ())
        _thread.start_new_thread(subscribe_swaps, ())
        xud_get_info()
    except:
        print("Failed to connect")


def handle_deposit(cmd):
    global user
    if user is None:
        print("Login first")
        return
    parts = cmd.split()
    if len(parts) < 2:
        print("Missing <currency>")
        return
    if len(parts) < 3:
        print("Missing <amount>")
        return
    currency = parts[1]
    amount = parts[2]
    user.balance[currency] = user.balance[currency] + Decimal(amount)


def print_help():
    print("login <user>")
    print("logout")
    print("buy/sell <quantity>[@<price>]")
    print("cancel <orderId>")
    print("balance [<currency>]")
    print("deposit <currency> <amount>")
    print("orderbook")
    print("connect [<host>] [<port>]")
    print("help")
    print("exit")


def print_balance(cmd):
    global user
    if user is None:
        print("Login first")
        return
    parts = cmd.split()
    if len(parts) == 1:
        for key in user.balance:
            print('%s: %s' % (key, user.balance[key]))
    else:
        print(user.balance[parts[1]])


def handle_login(cmd):
    global user
    parts = cmd.split()
    if len(parts) < 2:
        print("Missing user!")
        return
    name = parts[1]
    result = list(filter(lambda u: u.name == name, users))
    if len(result) == 0:
        print("No such user: ", name)
    user = result[0]


def print_orders(cmd):
    global user, orders, P, Q
    if user is None:
        print("Login first!")
        return
    result = list(filter(lambda x: x.user == user, orders))
    for order in result:
        print(order)


def run():
    global user, P, Q
    while True:
        if user is None:
            cmd = input('\n> ')
        else:
            cmd = input('\n(%s) > ' % (user.name))
        if cmd == 'exit':
            break
        elif cmd.startswith('login'):
            handle_login(cmd)
        elif cmd == 'logout':
            user = None
        elif cmd.startswith('buy') or cmd.startswith('sell'):
            place_order(cmd)
        elif cmd.startswith('cancel'):
            cancel_order(cmd)
        elif cmd.startswith('balance'):
            print_balance(cmd)
        elif cmd == 'orderbook':
            print_orderbook()
        elif cmd.startswith('connect'):
            handle_connect(cmd)
        elif cmd.startswith('deposit'):
            handle_deposit(cmd)
        elif cmd.startswith('orders'):
            print_orders(cmd)
        elif cmd == 'help':
            print_help()
        else:
            print('Bad command: ' + cmd)
            print('Type `help` for some helps')


def print_banner(banner):
    file = open(banner, 'r')
    print(file.read())


if __name__ == '__main__':
    print_banner(sys.argv[1])
    host = sys.argv[2]
    port = sys.argv[3]
    cert = sys.argv[4]
    run()
